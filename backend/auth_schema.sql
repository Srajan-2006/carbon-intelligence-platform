-- SIH1644 Mine Carbon Intelligence & Decarbonization Platform
-- Authentication schema
--
-- IMPORTANT: unlike schema.sql (which is dropped and rebuilt every time
-- seed_data.py runs, by design, so emissions/intervention data stays
-- deterministic and repeatable), this file uses CREATE TABLE IF NOT EXISTS
-- ONLY. It must NEVER drop the users table, so that re-seeding prototype
-- carbon data does not destroy registered accounts.

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('ADMIN','MINE_MANAGER','ANALYST')),
    mine_id       TEXT REFERENCES mine_master(mine_id),  -- NULL for ADMIN (all-mine access)
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT DEFAULT (datetime('now'))
);
