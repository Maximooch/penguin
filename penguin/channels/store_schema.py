"""SQLite schema for durable channel state."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS channel_bindings (
    address_key TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    directory TEXT,
    agent_id TEXT,
    agent_mode TEXT,
    settings_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL CHECK (version > 0),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_pairings (
    code_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    expected_user_id TEXT,
    state TEXT NOT NULL CHECK (
        state IN ('active', 'consumed', 'revoked', 'expired')
    ),
    expires_at REAL NOT NULL,
    consumed_by_user_id TEXT,
    consumed_chat_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS channel_pairings_expiry
    ON channel_pairings(state, expires_at);

CREATE TABLE IF NOT EXISTS channel_dm_authorizations (
    account_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    pairing_code_hash TEXT,
    created_at REAL NOT NULL,
    revoked_at REAL,
    PRIMARY KEY (account_id, user_id),
    FOREIGN KEY (pairing_code_hash) REFERENCES channel_pairings(code_hash)
);

CREATE TABLE IF NOT EXISTS channel_group_authorizations (
    platform TEXT NOT NULL,
    account_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    source_chat_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (platform, account_id, chat_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS channel_group_authorizations_source
    ON channel_group_authorizations(platform, account_id, source_chat_id);

CREATE TABLE IF NOT EXISTS channel_callbacks (
    callback_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    tool_call_id TEXT,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('pending', 'claimed', 'completed', 'dead', 'expired')
    ),
    claim_owner TEXT,
    lease_expires_at REAL,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL
);
CREATE INDEX IF NOT EXISTS channel_callbacks_expiry
    ON channel_callbacks(state, expires_at, lease_expires_at);

CREATE TABLE IF NOT EXISTS channel_ingress (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    account_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    lane_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('pending', 'retry', 'claimed', 'started', 'completed', 'dead')
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    claim_owner TEXT,
    lease_expires_at REAL,
    started_at REAL,
    last_error_class TEXT,
    last_error_message TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    UNIQUE (platform, account_id, event_id)
);
CREATE INDEX IF NOT EXISTS channel_ingress_claim
    ON channel_ingress(platform, account_id, state, next_attempt_at, sequence);
CREATE INDEX IF NOT EXISTS channel_ingress_lane
    ON channel_ingress(platform, account_id, lane_key, sequence, state);

CREATE TABLE IF NOT EXISTS channel_deliveries (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    account_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    lane_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_event_id TEXT,
    source_session_id TEXT,
    source_request_id TEXT,
    state TEXT NOT NULL CHECK (
        state IN ('pending', 'retry', 'claimed', 'delivered', 'dead')
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    claim_owner TEXT,
    lease_expires_at REAL,
    external_message_id TEXT,
    last_error_class TEXT,
    last_error_message TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    UNIQUE (platform, account_id, delivery_id),
    UNIQUE (platform, account_id, idempotency_key),
    FOREIGN KEY (platform, account_id, source_event_id)
        REFERENCES channel_ingress(platform, account_id, event_id)
);
CREATE INDEX IF NOT EXISTS channel_deliveries_claim
    ON channel_deliveries(platform, account_id, state, next_attempt_at, sequence);
CREATE INDEX IF NOT EXISTS channel_deliveries_lane
    ON channel_deliveries(platform, account_id, lane_key, sequence, state);

CREATE TABLE IF NOT EXISTS channel_pollers (
    platform TEXT NOT NULL,
    account_id TEXT NOT NULL,
    token_fingerprint TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at REAL,
    update_offset INTEGER,
    updated_at REAL NOT NULL,
    PRIMARY KEY (platform, account_id)
);

PRAGMA user_version=1;
"""


__all__ = ["SCHEMA_SQL"]
