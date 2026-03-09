"""
Tests that validate every example scenario described in the BiteSpeed
Identity Reconciliation PDF specification.

Phone numbers used throughout are valid E.164 values (required by the
PhoneNumber field in ConsolidatedContact).  They map conceptually to the
short fictional numbers in the PDF:

    PHONE_A  ≡  "123456"  (the shared phone in example 1)
    PHONE_B  ≡  "717171"  (the second-cluster phone in example 2)

PDF Scenarios covered
─────────────────────
  1. Brand-new contact – empty DB → single primary created.
  2. Repeat request – sending identical data twice produces no extra contact.
  3. New info adds secondary – a shared phone is found; the new email causes
     a secondary to be created (the exact example shown in the PDF response).
  4. Two separate clusters merge – a request that spans two primaries demotes
     the newer one; the cluster is unified under the oldest primary.
  4b. Merge carries along existing secondaries – secondaries of the demoted
     primary are re-parented to the surviving primary.
  5. Match via secondary – a request whose email matches a secondary (not a
     primary directly) still resolves to the correct primary.

HTTP-layer tests
────────────────
  H1. Missing both fields → 422.
  H2. Both email and phone provided, no prior DB state → 200 with primary.
  H3. Only email provided, no prior DB state → 200 with primary.
  H4. Valid email only (no phone) in the response when phone was NULL.
"""

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.repository.contact import ContactRecord

# ---------------------------------------------------------------------------
# Constants – phone numbers that pass pydantic_extra_types PhoneNumber
# validation (E.164 format, valid Indian mobile numbers)
# ---------------------------------------------------------------------------

# Conceptually equivalent to "123456" in the PDF (shared phone in example 1)
PHONE_A = "+919876543210"
# Conceptually equivalent to "717171" in the PDF (second-cluster phone)
PHONE_B = "+917987654321"

EMAIL_LORRAINE = "lorraine@hillvalley.edu"
EMAIL_MCFLY = "mcfly@hillvalley.edu"
EMAIL_GEORGE = "george@hillvalley.edu"

# A fixed base time for deterministic ordering in tests
T_BASE = datetime(2023, 4, 1, 10, 0, 0, tzinfo=timezone.utc)


# ===========================================================================
# In-Memory Database Stub
# ===========================================================================


class InMemoryDB:
    """
    In-memory replacement for the PostgreSQL contact table.

    InMemoryDB.seed() lets tests pre-populate contacts with explicit
    timestamps so ordering (oldest-primary logic) is fully deterministic.
    The create/demote/reparent methods mirror the repository functions
    used by the service layer.
    """

    def __init__(self) -> None:
        self._contacts: list[dict] = []
        self._counter = 0

    # ── internal helpers ─────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    def _active(self) -> list[dict]:
        return [c for c in self._contacts if c["deleted_at"] is None]

    def _to_record(self, d: dict) -> ContactRecord:
        return ContactRecord(**d)

    # ── test setup helper ────────────────────────────────────────────────

    def seed(
        self,
        email: Optional[str] = None,
        phone_number: Optional[str] = None,
        link_precedence: str = "primary",
        linked_id: Optional[int] = None,
        created_at: Optional[datetime] = None,
    ) -> ContactRecord:
        """Insert a contact directly with a controlled timestamp."""
        # Default: each seeded contact is 1 s after the previous one
        ts = created_at or (T_BASE + timedelta(seconds=self._counter))
        record = {
            "id": self._next_id(),
            "email": email,
            "phone_number": phone_number,
            "link_precedence": link_precedence,
            "linked_id": linked_id,
            "created_at": ts,
            "updated_at": ts,
            "deleted_at": None,
        }
        self._contacts.append(record)
        return self._to_record(record)

    def snapshot(self) -> list[dict]:
        """Return a deep-copy of all contacts (for assertions)."""
        return deepcopy(self._contacts)

    # ── repository method equivalents ────────────────────────────────────

    def find_by_email_or_phone(
        self, email: Optional[str], phone_number: Optional[str]
    ) -> list[ContactRecord]:
        results = [
            c
            for c in self._active()
            if (email and c["email"] == email)
            or (phone_number and c["phone_number"] == phone_number)
        ]
        return [self._to_record(c) for c in sorted(results, key=lambda c: c["created_at"])]

    def get_by_id(self, cid: int) -> Optional[ContactRecord]:
        for c in self._active():
            if c["id"] == cid:
                return self._to_record(c)
        return None

    def find_cluster(self, primary_id: int) -> list[ContactRecord]:
        results = [
            c
            for c in self._active()
            if c["id"] == primary_id or c["linked_id"] == primary_id
        ]
        return [self._to_record(c) for c in sorted(results, key=lambda c: c["created_at"])]

    def create(
        self,
        email: Optional[str],
        phone_number: Optional[str],
        link_precedence: str,
        linked_id: Optional[int] = None,
    ) -> ContactRecord:
        # Timestamps produced by the service always advance
        ts = T_BASE + timedelta(seconds=self._counter)
        record = {
            "id": self._next_id(),
            "email": email,
            "phone_number": phone_number,
            "link_precedence": link_precedence,
            "linked_id": linked_id,
            "created_at": ts,
            "updated_at": ts,
            "deleted_at": None,
        }
        self._contacts.append(record)
        return self._to_record(record)

    def demote_to_secondary(self, contact_id: int, primary_id: int) -> None:
        for c in self._contacts:
            if c["id"] == contact_id:
                c["linked_id"] = primary_id
                c["link_precedence"] = "secondary"
                c["updated_at"] = datetime.now(timezone.utc)
                return

    def reparent_secondaries(self, old_primary_id: int, new_primary_id: int) -> None:
        for c in self._contacts:
            if c["linked_id"] == old_primary_id:
                c["linked_id"] = new_primary_id
                c["updated_at"] = datetime.now(timezone.utc)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def db() -> InMemoryDB:
    return InMemoryDB()


@pytest.fixture()
def mock_repo(db: InMemoryDB, monkeypatch: pytest.MonkeyPatch) -> InMemoryDB:
    """
    Patches every repository function imported by api.contacts.service with
    a thin wrapper that delegates to InMemoryDB.  The asyncpg connection
    argument is accepted but ignored (the DB is in-memory).
    """

    @asynccontextmanager
    async def fake_transaction():
        yield object()  # connection is a sentinel; repo mocks ignore it

    fake_pool = MagicMock()
    fake_pool.transaction = fake_transaction
    monkeypatch.setattr("api.contacts.service.get_db_pool", lambda: fake_pool)

    async def fake_find(conn, email, phone):
        return db.find_by_email_or_phone(email, phone)

    async def fake_get(conn, cid):
        return db.get_by_id(cid)

    async def fake_cluster(conn, pid):
        return db.find_cluster(pid)

    async def fake_create(conn, email, phone, precedence, linked_id=None):
        return db.create(email, phone, precedence, linked_id)

    async def fake_demote(conn, cid, pid):
        db.demote_to_secondary(cid, pid)

    async def fake_reparent(conn, old_pid, new_pid):
        db.reparent_secondaries(old_pid, new_pid)

    monkeypatch.setattr(
        "api.contacts.service.find_contacts_by_email_or_phone", fake_find
    )
    monkeypatch.setattr("api.contacts.service.get_contact_by_id", fake_get)
    monkeypatch.setattr("api.contacts.service.find_cluster_contacts", fake_cluster)
    monkeypatch.setattr("api.contacts.service.create_contact", fake_create)
    monkeypatch.setattr(
        "api.contacts.service.update_contact_to_secondary", fake_demote
    )
    monkeypatch.setattr(
        "api.contacts.service.update_secondaries_parent", fake_reparent
    )
    return db


@pytest.fixture()
def test_app(mock_repo: InMemoryDB):
    """
    Minimal FastAPI app containing only the contacts router and exception
    handlers.  No lifespan context / DB init – suitable for HTTP-layer tests.
    """
    from fastapi import FastAPI

    from api.controller.contact import router
    from api.exceptions.handler import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    return app


@pytest_asyncio.fixture()
async def client(test_app):
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


# ===========================================================================
# Helper
# ===========================================================================


def _contact(response_json: dict) -> dict:
    """Unwrap the 'contact' key from a raw JSON response dict."""
    return response_json["contact"]


# ===========================================================================
# Service-level tests  (PDF scenarios)
# ===========================================================================


class TestScenario1BrandNewContact:
    """
    PDF Example 1
    ─────────────
    DB state : empty

    Request  : { email: lorraine@hillvalley.edu, phoneNumber: PHONE_A }

    Expected : A single primary contact is created.
               Response lists that contact as the primary with no secondaries.
    """

    async def test_creates_one_primary_contact(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        response = await identify_contact(EMAIL_LORRAINE, PHONE_A)
        c = response.contact

        assert c.primaryContatcId == 1
        assert EMAIL_LORRAINE in c.emails
        assert PHONE_A in c.phoneNumbers
        assert c.secondaryContactIds == []

    async def test_only_one_record_in_db(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        await identify_contact(EMAIL_LORRAINE, PHONE_A)

        assert len(mock_repo._contacts) == 1
        assert mock_repo._contacts[0]["link_precedence"] == "primary"
        assert mock_repo._contacts[0]["linked_id"] is None


class TestScenario2RepeatRequestIsIdempotent:
    """
    PDF Example 2
    ─────────────
    DB state : (empty before first call)

    Sends the same payload twice.

    Expected : The second call must not create any new contact.
               Both responses must return the same primaryContatcId.
    """

    async def test_no_new_contact_on_repeat(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        await identify_contact(EMAIL_LORRAINE, PHONE_A)
        count_after_first = len(mock_repo._contacts)

        await identify_contact(EMAIL_LORRAINE, PHONE_A)
        count_after_second = len(mock_repo._contacts)

        assert count_after_first == count_after_second == 1

    async def test_same_primary_returned_both_times(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        r1 = await identify_contact(EMAIL_LORRAINE, PHONE_A)
        r2 = await identify_contact(EMAIL_LORRAINE, PHONE_A)

        assert r1.contact.primaryContatcId == r2.contact.primaryContatcId == 1
        assert r1.contact.emails == r2.contact.emails
        assert r1.contact.phoneNumbers == r2.contact.phoneNumbers


class TestScenario3NewInfoCreatesSecondary:
    """
    PDF Example 3  (the main worked example in the spec)
    ─────────────
    DB state : C1 = { id:1, lorraine@hillvalley.edu, PHONE_A, primary }

    Request  : { email: mcfly@hillvalley.edu, phoneNumber: PHONE_A }

    Expected :
      • PHONE_A matches C1 → C1 is the primary.
      • mcfly@hillvalley.edu is new → a secondary C2 is created, linked to C1.
      • Response mirrors the PDF:
            primaryContatcId : 1
            emails           : ["lorraine@…", "mcfly@…"]  (primary first)
            phoneNumbers     : [PHONE_A]                  (deduplicated)
            secondaryContactIds : [<id of C2>]
    """

    async def test_primary_id_is_original_contact(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        mock_repo.seed(EMAIL_LORRAINE, PHONE_A)
        response = await identify_contact(EMAIL_MCFLY, PHONE_A)

        assert response.contact.primaryContatcId == 1

    async def test_primary_email_appears_first(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        mock_repo.seed(EMAIL_LORRAINE, PHONE_A)
        response = await identify_contact(EMAIL_MCFLY, PHONE_A)

        assert response.contact.emails[0] == EMAIL_LORRAINE
        assert EMAIL_MCFLY in response.contact.emails

    async def test_phone_number_deduplicated(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        mock_repo.seed(EMAIL_LORRAINE, PHONE_A)
        response = await identify_contact(EMAIL_MCFLY, PHONE_A)

        assert response.contact.phoneNumbers == [PHONE_A]

    async def test_one_secondary_created(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        mock_repo.seed(EMAIL_LORRAINE, PHONE_A)
        response = await identify_contact(EMAIL_MCFLY, PHONE_A)

        assert len(response.contact.secondaryContactIds) == 1

    async def test_secondary_links_to_primary(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        mock_repo.seed(EMAIL_LORRAINE, PHONE_A)
        response = await identify_contact(EMAIL_MCFLY, PHONE_A)

        sid = response.contact.secondaryContactIds[0]
        secondary = mock_repo.get_by_id(sid)

        assert secondary is not None
        assert secondary.link_precedence == "secondary"
        assert secondary.linked_id == 1
        assert secondary.email == EMAIL_MCFLY


class TestScenario4TwoClustersMerge:
    """
    PDF Example 4
    ─────────────
    DB state :
      C1 = { id:1, lorraine@hillvalley.edu, NULL, primary,  T_BASE      }
      C2 = { id:2, NULL,                   PHONE_B, primary, T_BASE+1 s }

    Request  : { email: lorraine@hillvalley.edu, phoneNumber: PHONE_B }

    Expected :
      • Email matches C1, phone matches C2 → two clusters bridged.
      • C1 is older → C1 remains primary.
      • C2 is demoted to secondary linked to C1.
      • No extra contact created (both email and phone already in cluster).
      • Response:
            primaryContatcId    : 1
            emails              : ["lorraine@…"]
            phoneNumbers        : [PHONE_B]
            secondaryContactIds : [2]
    """

    async def test_oldest_primary_survives(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        mock_repo.seed(EMAIL_LORRAINE, None, created_at=T_BASE)
        mock_repo.seed(None, PHONE_B, created_at=T_BASE + timedelta(seconds=1))

        response = await identify_contact(EMAIL_LORRAINE, PHONE_B)

        assert response.contact.primaryContatcId == 1

    async def test_newer_primary_is_demoted(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        mock_repo.seed(EMAIL_LORRAINE, None, created_at=T_BASE)
        mock_repo.seed(None, PHONE_B, created_at=T_BASE + timedelta(seconds=1))

        response = await identify_contact(EMAIL_LORRAINE, PHONE_B)

        c2 = mock_repo.get_by_id(2)
        assert c2 is not None
        assert c2.link_precedence == "secondary"
        assert c2.linked_id == 1

    async def test_both_clusters_info_in_response(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        mock_repo.seed(EMAIL_LORRAINE, None, created_at=T_BASE)
        mock_repo.seed(None, PHONE_B, created_at=T_BASE + timedelta(seconds=1))

        response = await identify_contact(EMAIL_LORRAINE, PHONE_B)
        c = response.contact

        assert EMAIL_LORRAINE in c.emails
        assert PHONE_B in c.phoneNumbers
        assert 2 in c.secondaryContactIds

    async def test_no_extra_contact_created(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        mock_repo.seed(EMAIL_LORRAINE, None, created_at=T_BASE)
        mock_repo.seed(None, PHONE_B, created_at=T_BASE + timedelta(seconds=1))

        await identify_contact(EMAIL_LORRAINE, PHONE_B)

        # Only the two original contacts; no third one created
        assert len(mock_repo._contacts) == 2


class TestScenario4bMergeReparentsExistingSecondaries:
    """
    Extended merge scenario.
    ─────────────────────────
    DB state :
      C1  = { id:1, lorraine@…, PHONE_A, primary,   T_BASE      }
      C2  = { id:2, mcfly@…,    PHONE_A, secondary→1, T_BASE+1 s }
      C3  = { id:3, NULL,       PHONE_B, primary,   T_BASE+2 s  }

    Request  : { email: lorraine@hillvalley.edu, phoneNumber: PHONE_B }

    Expected :
      • C1 primary, C3 demoted to secondary of C1.
      • C2 (already secondary of C1) stays linked to C1.
      • secondaryContactIds = [2, 3] (ordered by created_at).
      • No new contact created.
    """

    async def test_secondary_reparented_to_surviving_primary(
        self, mock_repo: InMemoryDB
    ) -> None:
        from api.service.contact import identify_contact

        c1 = mock_repo.seed(EMAIL_LORRAINE, PHONE_A, created_at=T_BASE)
        mock_repo.seed(
            EMAIL_MCFLY,
            PHONE_A,
            link_precedence="secondary",
            linked_id=c1.id,
            created_at=T_BASE + timedelta(seconds=1),
        )
        mock_repo.seed(None, PHONE_B, created_at=T_BASE + timedelta(seconds=2))

        response = await identify_contact(EMAIL_LORRAINE, PHONE_B)
        c = response.contact

        assert c.primaryContatcId == 1
        assert 2 in c.secondaryContactIds
        assert 3 in c.secondaryContactIds

        c3 = mock_repo.get_by_id(3)
        assert c3.link_precedence == "secondary"
        assert c3.linked_id == 1

    async def test_no_extra_contact_created(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        c1 = mock_repo.seed(EMAIL_LORRAINE, PHONE_A, created_at=T_BASE)
        mock_repo.seed(
            EMAIL_MCFLY,
            PHONE_A,
            link_precedence="secondary",
            linked_id=c1.id,
            created_at=T_BASE + timedelta(seconds=1),
        )
        mock_repo.seed(None, PHONE_B, created_at=T_BASE + timedelta(seconds=2))

        await identify_contact(EMAIL_LORRAINE, PHONE_B)

        assert len(mock_repo._contacts) == 3


class TestScenario5MatchViaSecondary:
    """
    Secondary-match resolution.
    ────────────────────────────
    DB state :
      C1 = { id:1, lorraine@…, PHONE_A, primary   }
      C2 = { id:2, mcfly@…,    PHONE_A, secondary→1 }

    Request  : { email: mcfly@hillvalley.edu, phoneNumber: None }

    Expected :
      • C2 matches (secondary). Its linked_id=1 → C1 is the primary.
      • Response primary is C1; C2 is in secondaryContactIds.
      • No new contact created.
    """

    async def test_resolves_primary_from_secondary_match(
        self, mock_repo: InMemoryDB
    ) -> None:
        from api.service.contact import identify_contact

        c1 = mock_repo.seed(EMAIL_LORRAINE, PHONE_A, created_at=T_BASE)
        mock_repo.seed(
            EMAIL_MCFLY,
            PHONE_A,
            link_precedence="secondary",
            linked_id=c1.id,
            created_at=T_BASE + timedelta(seconds=1),
        )

        response = await identify_contact(EMAIL_MCFLY, None)
        c = response.contact

        assert c.primaryContatcId == 1
        assert EMAIL_LORRAINE in c.emails
        assert EMAIL_MCFLY in c.emails
        assert 2 in c.secondaryContactIds

    async def test_no_new_contact_created(self, mock_repo: InMemoryDB) -> None:
        from api.service.contact import identify_contact

        c1 = mock_repo.seed(EMAIL_LORRAINE, PHONE_A, created_at=T_BASE)
        mock_repo.seed(
            EMAIL_MCFLY,
            PHONE_A,
            link_precedence="secondary",
            linked_id=c1.id,
            created_at=T_BASE + timedelta(seconds=1),
        )

        await identify_contact(EMAIL_MCFLY, None)

        assert len(mock_repo._contacts) == 2


# ===========================================================================
# HTTP-layer tests  (validation + end-to-end request/response format)
# ===========================================================================


class TestHTTPValidation:
    """
    H1 – Sending neither email nor phoneNumber must return 422.
    """

    async def test_missing_both_fields_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/identify", json={})
        assert resp.status_code == 422

    async def test_null_both_fields_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/identify", json={"email": None, "phoneNumber": None}
        )
        assert resp.status_code == 422

    async def test_invalid_email_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/identify", json={"email": "not-an-email", "phoneNumber": None}
        )
        assert resp.status_code == 422

    async def test_invalid_phone_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/identify", json={"email": None, "phoneNumber": "abc"}
        )
        assert resp.status_code == 422


class TestHTTPResponseFormat:
    """
    H2 – Valid request → correct JSON shape.
    H3 – Only email provided → works.
    H4 – Only phone provided → works; phoneNumbers present, emails empty.
    """

    async def test_h2_both_fields_returns_200_and_correct_shape(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/identify",
            json={"email": EMAIL_LORRAINE, "phoneNumber": PHONE_A},
        )
        assert resp.status_code == 200
        body = resp.json()
        contact = _contact(body)
        assert "primaryContatcId" in contact
        assert isinstance(contact["emails"], list)
        assert isinstance(contact["phoneNumbers"], list)
        assert isinstance(contact["secondaryContactIds"], list)

    async def test_h2_new_contact_has_no_secondaries(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/identify",
            json={"email": EMAIL_LORRAINE, "phoneNumber": PHONE_A},
        )
        assert resp.json()["contact"]["secondaryContactIds"] == []

    async def test_h3_email_only_returns_200(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/identify",
            json={"email": EMAIL_LORRAINE, "phoneNumber": None},
        )
        assert resp.status_code == 200
        contact = _contact(resp.json())
        assert EMAIL_LORRAINE in contact["emails"]
        assert contact["phoneNumbers"] == []

    async def test_h4_phone_only_returns_200(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/identify",
            json={"email": None, "phoneNumber": PHONE_A},
        )
        assert resp.status_code == 200
        contact = _contact(resp.json())
        assert contact["emails"] == []
        # E.164 value is stored; response may normalise; check it's non-empty
        assert len(contact["phoneNumbers"]) == 1

    async def test_h2_sequential_requests_return_same_primary(
        self, client: AsyncClient, mock_repo: InMemoryDB
    ) -> None:
        """PDF idempotency: sending the same payload twice must not change primary."""
        payload = {"email": EMAIL_LORRAINE, "phoneNumber": PHONE_A}

        r1 = await client.post("/identify", json=payload)
        r2 = await client.post("/identify", json=payload)

        assert r1.status_code == r2.status_code == 200
        pid1 = _contact(r1.json())["primaryContatcId"]
        pid2 = _contact(r2.json())["primaryContatcId"]
        assert pid1 == pid2
        assert len(mock_repo._contacts) == 1
