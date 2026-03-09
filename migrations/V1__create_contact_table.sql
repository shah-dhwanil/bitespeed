-- BiteSpeed Identity Reconciliation
-- V1: Create contact table

CREATE TABLE IF NOT EXISTS contact (
    id               SERIAL PRIMARY KEY,
    phone_number     VARCHAR(20),
    email            VARCHAR(255),
    linked_id        INTEGER REFERENCES contact(id) ON DELETE SET NULL,
    link_precedence  VARCHAR(10) NOT NULL
                         CHECK (link_precedence IN ('primary', 'secondary')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ
);

-- Partial index: fast lookup by email for active records
CREATE INDEX IF NOT EXISTS idx_contact_email
    ON contact(email)
    WHERE email IS NOT NULL AND deleted_at IS NULL;

-- Partial index: fast lookup by phone_number for active records
CREATE INDEX IF NOT EXISTS idx_contact_phone_number
    ON contact(phone_number)
    WHERE phone_number IS NOT NULL AND deleted_at IS NULL;

-- Index: fast cluster expansion (find all secondaries of a primary)
CREATE INDEX IF NOT EXISTS idx_contact_linked_id
    ON contact(linked_id)
    WHERE linked_id IS NOT NULL;
