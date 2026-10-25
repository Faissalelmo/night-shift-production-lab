-- Schema for the simulated payments back office.
-- Runs once, when the PostgreSQL volume is first created.

CREATE TABLE transactions (
    id               BIGSERIAL PRIMARY KEY,
    rrn              CHAR(12)       NOT NULL UNIQUE,      -- Retrieval Reference Number
    amount           NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    currency         CHAR(3)        NOT NULL DEFAULT 'MAD',
    value_date       DATE           NOT NULL,
    channel          TEXT           NOT NULL,             -- WALLET, CARD, INTERBANK, ...
    institution_code TEXT           NOT NULL,
    created_at       TIMESTAMPTZ    NOT NULL DEFAULT now()
);
CREATE INDEX transactions_created_at_idx ON transactions (created_at);

-- One row per settlement file received from the (simulated) clearing house.
-- sha256 makes a re-sent file detectable even under a different name.
CREATE TABLE settlement_files (
    id         BIGSERIAL PRIMARY KEY,
    file_name  TEXT        NOT NULL UNIQUE,
    sha256     CHAR(64)    NOT NULL UNIQUE,
    row_count  INTEGER     NOT NULL DEFAULT 0,
    loaded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id     TEXT
);

CREATE TABLE settlement_rows (
    id               BIGSERIAL PRIMARY KEY,
    file_id          BIGINT         NOT NULL REFERENCES settlement_files (id),
    rrn              CHAR(12)       NOT NULL UNIQUE,      -- the idempotency key for imports
    amount           NUMERIC(14, 2) NOT NULL,
    currency         CHAR(3)        NOT NULL,
    value_date       DATE           NOT NULL,
    institution_code TEXT           NOT NULL
);

CREATE TABLE reconciliation_results (
    id                 BIGSERIAL PRIMARY KEY,
    rrn                CHAR(12)       NOT NULL UNIQUE,    -- one verdict per RRN: reruns can't duplicate
    status             TEXT           NOT NULL CHECK (status IN
                         ('MATCHED', 'AMOUNT_MISMATCH', 'DATE_MISMATCH',
                          'MISSING_IN_SETTLEMENT', 'UNKNOWN_RRN')),
    txn_amount         NUMERIC(14, 2),
    settled_amount     NUMERIC(14, 2),
    txn_value_date     DATE,
    settled_value_date DATE,
    run_id             TEXT           NOT NULL,
    detected_at        TIMESTAMPTZ    NOT NULL DEFAULT now(),
    late_settlement    BOOLEAN        NOT NULL DEFAULT false,
    exported_at        TIMESTAMPTZ,
    export_file        TEXT
);
CREATE INDEX reconciliation_unexported_idx
    ON reconciliation_results (id) WHERE status <> 'MATCHED' AND exported_at IS NULL;

-- Run history, read by the status page.
CREATE TABLE job_runs (
    run_id         TEXT PRIMARY KEY,
    job            TEXT        NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL,
    finished_at    TIMESTAMPTZ NOT NULL,
    status         TEXT        NOT NULL CHECK (status IN ('success', 'failed')),
    did_work       BOOLEAN     NOT NULL,   -- false = ran fine but had no input (e.g. no file)
    rows_processed INTEGER     NOT NULL DEFAULT 0,
    error_type     TEXT,
    message        TEXT
);
CREATE INDEX job_runs_job_finished_idx ON job_runs (job, finished_at DESC);

-- Switches flipped by scripts/inject.sh to simulate incidents (slow_query, slow_page).
CREATE TABLE lab_faults (
    name   TEXT PRIMARY KEY,
    value  NUMERIC     NOT NULL,
    set_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
