from typing import Optional

import asyncpg
import structlog

from api.models.contact import ConsolidatedContact, IdentifyResponse
from api.repository.contact import (
    ContactRecord,
    create_contact,
    find_cluster_contacts,
    find_contacts_by_email_or_phone,
    get_contact_by_id,
    update_contact_to_secondary,
    update_secondaries_parent,
)
from api.database import get_db_pool
from api.exceptions.contact import ContactNotFoundException

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Private helpers (DRY building blocks)
# ---------------------------------------------------------------------------


def _collect_primary_ids(contacts: list[ContactRecord]) -> set[int]:
    """
    Extract the set of primary contact IDs reachable from a list of contacts.

    For primary contacts their own id is used; for secondaries the linked_id is
    used.  Corrupt secondaries with no linked_id are treated as primaries.
    """
    ids: set[int] = set()
    for c in contacts:
        if c.link_precedence == "primary":
            ids.add(c.id)
        elif c.linked_id is not None:
            ids.add(c.linked_id)
        else:
            # Data consistency safeguard: secondary without a linked_id
            ids.add(c.id)
    return ids


async def _load_primaries(
    conn: asyncpg.Connection, primary_ids: set[int]
) -> list[ContactRecord]:
    """Fetch all ContactRecord objects for the given set of primary IDs."""
    primaries: list[ContactRecord] = []
    for pid in primary_ids:
        contact = await get_contact_by_id(conn, pid)
        if contact is None:
            raise ContactNotFoundException(pid)
        primaries.append(contact)
    return primaries


async def _merge_non_oldest_primaries(
    conn: asyncpg.Connection,
    primaries: list[ContactRecord],
    oldest: ContactRecord,
) -> None:
    """
    Demote every primary that is not the oldest one.

    For each non-oldest primary:
      1. Re-link its secondaries to the oldest primary.
      2. Demote it to secondary, linked to the oldest primary.
    """
    for p in primaries:
        if p.id == oldest.id:
            continue
        await update_secondaries_parent(conn, p.id, oldest.id)
        await update_contact_to_secondary(conn, p.id, oldest.id)


def _has_new_info(
    cluster: list[ContactRecord],
    email: Optional[str],
    phone_number: Optional[str],
) -> bool:
    """Return True if the request brings at least one email or phone not yet in the cluster."""
    existing_emails = {c.email for c in cluster if c.email}
    existing_phones = {c.phone_number for c in cluster if c.phone_number}
    email_is_new = email is not None and email not in existing_emails
    phone_is_new = phone_number is not None and phone_number not in existing_phones
    return email_is_new or phone_is_new


def _build_response(
    primary: ContactRecord, cluster: list[ContactRecord]
) -> IdentifyResponse:
    """
    Assemble the IdentifyResponse from a primary contact and its full cluster.

    The primary's email and phone always appear first in their respective lists.
    All values are deduplicated while preserving insertion order.
    """
    emails: list[str] = []
    phone_numbers: list[str] = []
    secondary_ids: list[int] = []
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()

    def _add_contact_info(contact: ContactRecord) -> None:
        if contact.email and contact.email not in seen_emails:
            emails.append(contact.email)
            seen_emails.add(contact.email)
        if contact.phone_number and contact.phone_number not in seen_phones:
            phone_numbers.append(contact.phone_number)
            seen_phones.add(contact.phone_number)

    # Primary first
    _add_contact_info(primary)

    # Secondaries in ascending created_at order
    for contact in cluster:
        if contact.id == primary.id:
            continue
        secondary_ids.append(contact.id)
        _add_contact_info(contact)

    return IdentifyResponse(
        contact=ConsolidatedContact(
            primaryContatcId=primary.id,
            emails=emails,
            phoneNumbers=phone_numbers,
            secondaryContactIds=secondary_ids,
        )
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def identify_contact(
    email: Optional[str],
    phone_number: Optional[str],
) -> IdentifyResponse:
    """
    Identify and consolidate a contact by email and/or phone number.

    The entire operation runs inside a single database transaction to guarantee
    atomicity even under concurrent requests.
    """
    db = get_db_pool()

    async with db.transaction() as conn:
        # Step 1: Find all directly matching contacts
        matching = await find_contacts_by_email_or_phone(conn, email, phone_number)
        logger.debug("identify_contact: found matching contacts", count=len(matching))

        # Step 2: No matches → brand-new primary contact
        if not matching:
            contact = await create_contact(conn, email, phone_number, "primary")
            logger.info("identify_contact: created new primary", contact_id=contact.id)
            return _build_response(contact, [contact])

        # Step 3: Determine the set of primary IDs reachable from the matches
        primary_ids = _collect_primary_ids(matching)

        # Step 4: Load all primary records and find the oldest one
        primaries = await _load_primaries(conn, primary_ids)
        oldest = min(primaries, key=lambda c: c.created_at)
        logger.debug(
            "identify_contact: resolved primaries",
            oldest_id=oldest.id,
            total_primaries=len(primaries),
        )

        # Step 5: Merge non-oldest primaries into the oldest
        await _merge_non_oldest_primaries(conn, primaries, oldest)

        # Step 6: Fetch the refreshed full cluster
        cluster = await find_cluster_contacts(conn, oldest.id)

        # Step 7: If the request introduces new info, record a new secondary
        if _has_new_info(cluster, email, phone_number):
            new_secondary = await create_contact(
                conn, email, phone_number, "secondary", linked_id=oldest.id
            )
            logger.info(
                "identify_contact: created secondary for new info",
                secondary_id=new_secondary.id,
                primary_id=oldest.id,
            )
            cluster = await find_cluster_contacts(conn, oldest.id)

        # Step 8: Build and return the consolidated response
        return _build_response(oldest, cluster)
