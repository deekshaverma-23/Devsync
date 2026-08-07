-- DevSync demo database

CREATE TABLE IF NOT EXISTS users (
    id                  SERIAL PRIMARY KEY,
    email               TEXT NOT NULL UNIQUE,
    password_reset_at   TIMESTAMP,
    last_login_at       TIMESTAMP,
    created_at          TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    status          TEXT NOT NULL,   -- PENDING, PROCESSING, COMPLETED, CANCELLED
    checkout_token  TEXT,            -- same token = same checkout attempt
    created_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
    id                     SERIAL PRIMARY KEY,
    order_id               INTEGER NOT NULL REFERENCES orders(id),
    status                 TEXT NOT NULL,  -- SUCCESS, FAILED, PENDING
    webhook_received_at    TIMESTAMP,
    created_at             TIMESTAMP NOT NULL DEFAULT now()
);

-- ---------- Seed users ----------
INSERT INTO users (email, password_reset_at, last_login_at) VALUES
('alice@example.com', now() - interval '2 days',  now() - interval '2 days'),
('bob@example.com',   now() - interval '1 days',  NULL),                  -- AUTH-211: reset, never logged in since
('carol@example.com', now() - interval '3 days',  NULL),                 -- AUTH-211
('dave@example.com',  NULL,                        now() - interval '5 days'),
('erin@example.com',  now() - interval '6 hours',  NULL);                -- AUTH-211

-- ---------- Seed orders + payments ----------
INSERT INTO orders (user_id, status, checkout_token, created_at) VALUES
(1, 'PROCESSING', 'chk-1001', now() - interval '3 hours'),
(1, 'PROCESSING', 'chk-1002', now() - interval '2 hours'),
(4, 'COMPLETED',  'chk-1003', now() - interval '1 day'),
(4, 'PROCESSING', 'chk-1004', now() - interval '40 minutes');

INSERT INTO payments (order_id, status, webhook_received_at, created_at) VALUES
(1, 'SUCCESS', NULL,                          now() - interval '3 hours'),  -- webhook never arrived
(2, 'SUCCESS', now() - interval '2 hours',    now() - interval '2 hours'), -- webhook late, still unsynced
(3, 'SUCCESS', now() - interval '1 day',      now() - interval '1 day'),   -- healthy case
(4, 'SUCCESS', NULL,                          now() - interval '40 minutes');

-- ORD-312 evidence: two orders sharing the same checkout_token (duplicate order bug)
INSERT INTO orders (user_id, status, checkout_token, created_at) VALUES
(3, 'PENDING', 'chk-2050', now() - interval '10 minutes'),
(3, 'PENDING', 'chk-2050', now() - interval '10 minutes');

-- ---------- Read-only role for the MCP server ----------
-- Run once as a superuser against the target database. The MCP server
-- must always connect using this role, never the table-owning role.
-- This is the "enforce it technically, not just via prompt" requirement.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'devsync_readonly') THEN
        CREATE ROLE devsync_readonly LOGIN PASSWORD 'devsync_readonly_pw';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE devsync TO devsync_readonly;
GRANT USAGE ON SCHEMA public TO devsync_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO devsync_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO devsync_readonly;
-- No INSERT / UPDATE / DELETE / DDL grants are ever given to this role.
