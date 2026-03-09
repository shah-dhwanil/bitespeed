from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
import asyncpg
import structlog

from api.exceptions.contact import ContactDatabaseError

logger = structlog.get_logger(__name__)


class ContactRecord(BaseModel):
    id: int
    phone_number: Optional[str]
    email: Optional[str]
    linked_id: Optional[int]
    link_precedence: str  # 'primary' | 'secondary'
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]


def _record_to_contact(record: asyncpg.Record) -> ContactRecord:
    return ContactRecord(
        id=record["id"],
        phone_number=record["phone_number"],
        email=record["email"],
        linked_id=record["linked_id"],
        link_precedence=record["link_precedence"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        deleted_at=record["deleted_at"],
    )


async def find_contacts_by_email_or_phone(
    conn: asyncpg.Connection,
    email: Optional[str],
    phone_number: Optional[str],
) -> list[ContactRecord]:
    try:
        rows = await conn.fetch(
            """
            SELECT * FROM bitespeed.contact
            WHERE deleted_at IS NULL
              AND (
                ($1::TEXT IS NOT NULL AND email = $1)
                OR ($2::TEXT IS NOT NULL AND phone_number = $2)
              )
            ORDER BY created_at ASC
            """,
            email,
            phone_number,
        )
        return [_record_to_contact(r) for r in rows]
    except Exception as exc:
        logger.error("find_contacts_by_email_or_phone failed", error=str(exc))
        raise ContactDatabaseError(
            f"Failed to find contacts by email or phone: {exc}"
        ) from exc


async def get_contact_by_id(
    conn: asyncpg.Connection,
    contact_id: int,
) -> Optional[ContactRecord]:
    try:
        row = await conn.fetchrow(
            "SELECT * FROM bitespeed.contact WHERE id = $1 AND deleted_at IS NULL",
            contact_id,
        )
        return _record_to_contact(row) if row else None
    except Exception as exc:
        logger.error("get_contact_by_id failed", contact_id=contact_id, error=str(exc))
        raise ContactDatabaseError(
            f"Failed to fetch contact with id {contact_id}: {exc}"
        ) from exc


async def find_cluster_contacts(
    conn: asyncpg.Connection,
    primary_id: int,
) -> list[ContactRecord]:
    """Return the primary contact and all its direct secondaries, ordered by created_at."""
    try:
        rows = await conn.fetch(
            """
            SELECT * FROM bitespeed.contact
            WHERE deleted_at IS NULL
              AND (id = $1 OR linked_id = $1)
            ORDER BY created_at ASC
            """,
            primary_id,
        )
        return [_record_to_contact(r) for r in rows]
    except Exception as exc:
        logger.error("find_cluster_contacts failed", primary_id=primary_id, error=str(exc))
        raise ContactDatabaseError(
            f"Failed to fetch cluster for primary {primary_id}: {exc}"
        ) from exc


async def create_contact(
    conn: asyncpg.Connection,
    email: Optional[str],
    phone_number: Optional[str],
    link_precedence: str,
    linked_id: Optional[int] = None,
) -> ContactRecord:
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO bitespeed.contact (email, phone_number, link_precedence, linked_id, created_at, updated_at)
            VALUES ($1, $2, $3, $4, NOW(), NOW())
            RETURNING *
            """,
            email,
            phone_number,
            link_precedence,
            linked_id,
        )
        return _record_to_contact(row)
    except Exception as exc:
        logger.error("create_contact failed", error=str(exc))
        raise ContactDatabaseError(f"Failed to create contact: {exc}") from exc


async def update_contact_to_secondary(
    conn: asyncpg.Connection,
    contact_id: int,
    primary_id: int,
) -> None:
    """Demote a primary contact to secondary, linking it to the given primary."""
    try:
        await conn.execute(
            """
            UPDATE bitespeed.contact
            SET linked_id = $2,
                link_precedence = 'secondary',
                updated_at = NOW()
            WHERE id = $1 AND deleted_at IS NULL
            """,
            contact_id,
            primary_id,
        )
    except Exception as exc:
        logger.error(
            "update_contact_to_secondary failed",
            contact_id=contact_id,
            primary_id=primary_id,
            error=str(exc),
        )
        raise ContactDatabaseError(
            f"Failed to demote contact {contact_id} to secondary: {exc}"
        ) from exc


async def update_secondaries_parent(
    conn: asyncpg.Connection,
    old_primary_id: int,
    new_primary_id: int,
) -> None:
    """Re-link all secondaries that point to old_primary_id so they point to new_primary_id."""
    try:
        await conn.execute(
            """
            UPDATE bitespeed.contact
            SET linked_id = $2,
                updated_at = NOW()
            WHERE linked_id = $1 AND deleted_at IS NULL
            """,
            old_primary_id,
            new_primary_id,
        )
    except Exception as exc:
        logger.error(
            "update_secondaries_parent failed",
            old_primary_id=old_primary_id,
            new_primary_id=new_primary_id,
            error=str(exc),
        )
        raise ContactDatabaseError(
            f"Failed to re-link secondaries from {old_primary_id} to {new_primary_id}: {exc}"
        ) from exc
