CREATE TABLE IF NOT EXISTS shipments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bl_no           TEXT UNIQUE NOT NULL,
    carrier         TEXT,
    vessel          TEXT,
    imo_no          TEXT,
    eta             TEXT,
    eta_prev_kst    TEXT,
    eta_changed     INTEGER NOT NULL DEFAULT 0,
    location        TEXT,
    lat             REAL,
    lon             REAL,
    bl_refreshed_at TEXT,
    loc_refreshed_at TEXT,
    memo            TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eta_snapshots (
    shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    kst_date    TEXT NOT NULL,
    eta         TEXT,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (shipment_id, kst_date)
);

CREATE INDEX IF NOT EXISTS idx_shipments_bl ON shipments(bl_no);
