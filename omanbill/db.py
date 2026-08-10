"""قاعدة البيانات (SQLite) وتعريف الجداول.

كل بيانات المنشأة معزولة بـ org_id. أي استعلام يقرأ بيانات مشترك يجب أن
يمرّر org_id، حتى لا تتسرّب بيانات منشأة إلى أخرى.
"""

import os
import sqlite3
import threading

DEFAULT_DB_PATH = os.environ.get(
    "OMANBILL_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "omanbill.db"),
)

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- المنشأة (المشترك). كل حساب يمثّل منشأة واحدة.
CREATE TABLE IF NOT EXISTS orgs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    vat_number        TEXT    NOT NULL DEFAULT '',   -- رقم التسجيل الضريبي
    cr_number         TEXT    NOT NULL DEFAULT '',   -- رقم السجل التجاري
    address           TEXT    NOT NULL DEFAULT '',
    phone             TEXT    NOT NULL DEFAULT '',
    email             TEXT    NOT NULL DEFAULT '',
    invoice_prefix    TEXT    NOT NULL DEFAULT 'INV',
    next_invoice_no   INTEGER NOT NULL DEFAULT 1,
    plan              TEXT    NOT NULL DEFAULT 'free',
    created_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id        INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    email         TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL DEFAULT '',
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id      INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    vat_number  TEXT    NOT NULL DEFAULT '',
    phone       TEXT    NOT NULL DEFAULT '',
    email       TEXT    NOT NULL DEFAULT '',
    address     TEXT    NOT NULL DEFAULT '',
    notes       TEXT    NOT NULL DEFAULT '',
    archived    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customers_org ON customers(org_id, archived);

-- كتالوج السلع والخدمات، لتسريع إدخال الفواتير
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id       INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    unit         TEXT    NOT NULL DEFAULT 'قطعة',
    unit_price   INTEGER NOT NULL DEFAULT 0,          -- بالبيسة
    vat_category TEXT    NOT NULL DEFAULT 'standard',
    archived     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_org ON items(org_id, archived);

-- الفواتير. المجاميع مخزّنة بالبيسة ومحسوبة على الخادم من البنود،
-- ولا تُقبل أبدًا من الواجهة.
CREATE TABLE IF NOT EXISTS invoices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id         INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    customer_id    INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    number         TEXT    NOT NULL,
    issue_date     TEXT    NOT NULL,
    due_date       TEXT    NOT NULL DEFAULT '',
    status         TEXT    NOT NULL DEFAULT 'draft',  -- draft/sent/paid/cancelled
    notes          TEXT    NOT NULL DEFAULT '',
    gross_total    INTEGER NOT NULL DEFAULT 0,
    discount_total INTEGER NOT NULL DEFAULT 0,
    taxable_total  INTEGER NOT NULL DEFAULT 0,
    vat_total      INTEGER NOT NULL DEFAULT 0,
    grand_total    INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    UNIQUE (org_id, number)
);
CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices(org_id, issue_date DESC);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(org_id, customer_id);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id    INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL DEFAULT 0,
    description   TEXT    NOT NULL,
    unit          TEXT    NOT NULL DEFAULT 'قطعة',
    quantity      INTEGER NOT NULL DEFAULT 1000,      -- أجزاء الألف
    unit_price    INTEGER NOT NULL DEFAULT 0,         -- بالبيسة
    discount      INTEGER NOT NULL DEFAULT 0,         -- بالبيسة
    vat_category  TEXT    NOT NULL DEFAULT 'standard',
    vat_rate_bp   INTEGER NOT NULL DEFAULT 500,
    taxable       INTEGER NOT NULL DEFAULT 0,
    vat_amount    INTEGER NOT NULL DEFAULT 0,
    line_total    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_lines_invoice ON invoice_lines(invoice_id, position);

CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id     INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    amount     INTEGER NOT NULL,                      -- بالبيسة
    paid_on    TEXT    NOT NULL,
    method     TEXT    NOT NULL DEFAULT 'cash',
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL,
    expires_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


def connect(db_path: str = None) -> sqlite3.Connection:
    """يُرجع اتصالًا خاصًا بالخيط الحالي.

    اتصالات SQLite ليست آمنة للمشاركة بين الخيوط، والخادم متعدد الخيوط،
    فلكل خيط اتصاله الخاص.
    """
    path = db_path or DEFAULT_DB_PATH
    existing = getattr(_local, "conn", None)
    if existing is not None and getattr(_local, "path", None) == path:
        return existing

    if existing is not None:
        existing.close()

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _local.conn = conn
    _local.path = path
    return conn


def init_db(db_path: str = None) -> sqlite3.Connection:
    """ينشئ الجداول إن لم تكن موجودة."""
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def close():
    """يغلق اتصال الخيط الحالي (يُستخدم في الاختبارات)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
        _local.path = None


def query(conn, sql: str, params=()) -> list:
    return conn.execute(sql, params).fetchall()


def query_one(conn, sql: str, params=()):
    return conn.execute(sql, params).fetchone()


def execute(conn, sql: str, params=()) -> sqlite3.Cursor:
    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor


def row_to_dict(row) -> dict:
    return dict(row) if row is not None else None
