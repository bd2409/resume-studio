"""Tiny SQLite store for orders. One row per purchase."""
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id              TEXT PRIMARY KEY,
    token           TEXT UNIQUE NOT NULL,
    created_at      TEXT NOT NULL,
    customer_name   TEXT NOT NULL,
    email           TEXT NOT NULL,
    phone           TEXT NOT NULL,
    job_description TEXT NOT NULL,
    files_json      TEXT NOT NULL,
    status          TEXT NOT NULL,          -- awaiting_payment, paid, generating, ready, failed
    amount_paise    INTEGER NOT NULL,
    rzp_order_id    TEXT,
    rzp_payment_id  TEXT,
    paid_at         TEXT,
    regenerations   INTEGER NOT NULL DEFAULT 0,
    progress        TEXT NOT NULL DEFAULT '',
    error           TEXT NOT NULL DEFAULT '',
    resume_json     TEXT,
    notes_json      TEXT,
    profile_json    TEXT,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_rzp ON orders (rzp_order_id);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def create_order(customer_name, email, phone, job_description, files, amount_paise):
    order_id = "ord_" + secrets.token_hex(6)
    token = secrets.token_urlsafe(24)
    with conn() as c:
        c.execute(
            "INSERT INTO orders (id, token, created_at, customer_name, email, phone, job_description,"
            " files_json, status, amount_paise, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (order_id, token, now(), customer_name, email, phone, job_description,
             json.dumps(files), "awaiting_payment", amount_paise, now()),
        )
    return get_by_id(order_id)


def get_by_token(token):
    with conn() as c:
        row = c.execute("SELECT * FROM orders WHERE token = ?", (token,)).fetchone()
    return dict(row) if row else None


def get_by_id(order_id):
    with conn() as c:
        row = c.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return dict(row) if row else None


def get_by_rzp_order(rzp_order_id):
    with conn() as c:
        row = c.execute("SELECT * FROM orders WHERE rzp_order_id = ?", (rzp_order_id,)).fetchone()
    return dict(row) if row else None


def update(order_id, **fields):
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE orders SET {cols} WHERE id = ?", (*fields.values(), order_id))


def mark_paid(order_id, payment_id):
    """Mark paid exactly once. Returns True only for the call that flipped the status."""
    with conn() as c:
        cur = c.execute(
            "UPDATE orders SET status = 'paid', rzp_payment_id = ?, paid_at = ?, updated_at = ?"
            " WHERE id = ? AND status = 'awaiting_payment'",
            (payment_id, now(), now(), order_id),
        )
        return cur.rowcount == 1


def recent(limit=200):
    with conn() as c:
        rows = c.execute(
            "SELECT id, token, created_at, customer_name, email, phone, status, amount_paise,"
            " rzp_payment_id, regenerations, error FROM orders ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def expired_orders(before_iso):
    with conn() as c:
        rows = c.execute("SELECT id FROM orders WHERE created_at < ?", (before_iso,)).fetchall()
    return [r["id"] for r in rows]


def purge_content(order_id):
    with conn() as c:
        c.execute(
            "UPDATE orders SET job_description = '', files_json = '[]', resume_json = NULL,"
            " profile_json = NULL, notes_json = NULL, updated_at = ? WHERE id = ?",
            (now(), order_id),
        )
