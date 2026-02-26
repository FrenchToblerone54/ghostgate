import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from nanoid import generate

DB_PATH = os.getenv("DB_PATH", "ghostgate.db")

@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()

SCHEMA_VERSION = 4

def init_db():
    with _conn() as c:
        user_ver = int(c.execute("PRAGMA user_version").fetchone()[0] or 0)
        has_tables = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('nodes','subscriptions','subscription_nodes','access_logs') LIMIT 1").fetchone() is not None
        def _col_exists(table, col):
            return any(r[1] == col for r in c.execute(f"PRAGMA table_info({table})").fetchall())
        def _tbl_exists(name):
            return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
        if user_ver == 0 and not has_tables:
            c.executescript("""
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    proxy_url TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE node_inbounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    inbound_id INTEGER NOT NULL,
    name TEXT,
    traffic_multiplier REAL DEFAULT 1.0,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE subscriptions (
    id TEXT PRIMARY KEY,
    comment TEXT,
    data_gb REAL DEFAULT 0,
    days INTEGER DEFAULT 0,
    ip_limit INTEGER DEFAULT 0,
    used_bytes INTEGER DEFAULT 0,
    expire_at TIMESTAMP,
    enabled INTEGER DEFAULT 1,
    show_multiplier INTEGER DEFAULT 1,
    expire_after_first_use_seconds INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE subscription_nodes (
    sub_id TEXT NOT NULL,
    node_id INTEGER NOT NULL,
    client_uuid TEXT NOT NULL,
    email TEXT NOT NULL,
    client_disabled INTEGER DEFAULT 0,
    "order" INTEGER DEFAULT 0,
    PRIMARY KEY (sub_id, node_id),
    FOREIGN KEY (sub_id) REFERENCES subscriptions(id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES node_inbounds(id) ON DELETE CASCADE
);
CREATE TABLE access_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sub_id TEXT NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sub_id) REFERENCES subscriptions(id) ON DELETE CASCADE
);
CREATE INDEX idx_al_sub ON access_logs(sub_id);
            """)
            c.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            return
        c.executescript("""
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    inbound_id INTEGER NOT NULL,
    proxy_url TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    comment TEXT,
    data_gb REAL DEFAULT 0,
    days INTEGER DEFAULT 0,
    ip_limit INTEGER DEFAULT 0,
    used_bytes INTEGER DEFAULT 0,
    expire_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS subscription_nodes (
    sub_id TEXT NOT NULL,
    node_id INTEGER NOT NULL,
    client_uuid TEXT NOT NULL,
    email TEXT NOT NULL,
    PRIMARY KEY (sub_id, node_id),
    FOREIGN KEY (sub_id) REFERENCES subscriptions(id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS access_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sub_id TEXT NOT NULL,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sub_id) REFERENCES subscriptions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_al_sub ON access_logs(sub_id);
        """)
        if user_ver < 1:
            if not _col_exists("subscriptions", "enabled"):
                c.execute("ALTER TABLE subscriptions ADD COLUMN enabled INTEGER DEFAULT 1")
            if not _col_exists("subscriptions", "show_multiplier"):
                c.execute("ALTER TABLE subscriptions ADD COLUMN show_multiplier INTEGER DEFAULT 1")
            if not _col_exists("access_logs", "ip_address"):
                c.execute("ALTER TABLE access_logs ADD COLUMN ip_address TEXT")
            if not _col_exists("access_logs", "user_agent"):
                c.execute("ALTER TABLE access_logs ADD COLUMN user_agent TEXT")
            if not _col_exists("nodes", "traffic_multiplier"):
                c.execute("ALTER TABLE nodes ADD COLUMN traffic_multiplier REAL DEFAULT 1.0")
            if not _col_exists("subscription_nodes", "client_disabled"):
                c.execute("ALTER TABLE subscription_nodes ADD COLUMN client_disabled INTEGER DEFAULT 0")
            c.execute("PRAGMA user_version=1")
        if user_ver < 2:
            if not _col_exists("subscriptions", "expire_after_first_use_seconds"):
                c.execute("ALTER TABLE subscriptions ADD COLUMN expire_after_first_use_seconds INTEGER DEFAULT 0")
            c.execute("PRAGMA user_version=2")
        if user_ver < 3:
            c.execute("PRAGMA foreign_keys=OFF")
            if not _tbl_exists("node_inbounds"):
                c.execute("""CREATE TABLE node_inbounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    inbound_id INTEGER NOT NULL,
    name TEXT,
    traffic_multiplier REAL DEFAULT 1.0,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""")
            if _col_exists("nodes", "inbound_id"):
                c.execute("""INSERT OR IGNORE INTO node_inbounds (id, node_id, inbound_id, name, traffic_multiplier, enabled, created_at)
SELECT n.id,
       (SELECT MIN(p.id) FROM nodes p WHERE p.address=n.address AND p.username=n.username AND p.password=n.password),
       n.inbound_id, n.name, COALESCE(n.traffic_multiplier, 1.0), n.enabled, n.created_at
FROM nodes n""")
                c.execute("INSERT OR REPLACE INTO sqlite_sequence (name, seq) SELECT 'node_inbounds', COALESCE(MAX(id), 0) FROM node_inbounds")
            if not _tbl_exists("subscription_nodes_v3"):
                c.execute("""CREATE TABLE subscription_nodes_v3 (
    sub_id TEXT NOT NULL,
    node_id INTEGER NOT NULL,
    client_uuid TEXT NOT NULL,
    email TEXT NOT NULL,
    client_disabled INTEGER DEFAULT 0,
    PRIMARY KEY (sub_id, node_id),
    FOREIGN KEY (sub_id) REFERENCES subscriptions(id) ON DELETE CASCADE,
    FOREIGN KEY (node_id) REFERENCES node_inbounds(id) ON DELETE CASCADE
)""")
            c.execute("INSERT OR IGNORE INTO subscription_nodes_v3 SELECT * FROM subscription_nodes")
            c.execute("DROP TABLE IF EXISTS subscription_nodes")
            c.execute("ALTER TABLE subscription_nodes_v3 RENAME TO subscription_nodes")
            if _col_exists("nodes", "inbound_id"):
                c.execute("DELETE FROM nodes WHERE id NOT IN (SELECT MIN(id) FROM nodes GROUP BY address, username, password)")
                c.execute("ALTER TABLE nodes DROP COLUMN inbound_id")
            if _col_exists("nodes", "traffic_multiplier"):
                c.execute("ALTER TABLE nodes DROP COLUMN traffic_multiplier")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA user_version=3")
        if user_ver < 4:
            if not _col_exists("subscription_nodes", "order"):
                c.execute('ALTER TABLE subscription_nodes ADD COLUMN "order" INTEGER DEFAULT 0')
                c.execute('UPDATE subscription_nodes SET "order" = node_id')
            c.execute("PRAGMA user_version=4")

def add_node(name, address, username, password, proxy_url=None):
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO nodes (name, address, username, password, proxy_url) VALUES (?,?,?,?,?)",
            (name, address, username, password, proxy_url)
        )
        return cur.lastrowid

def get_nodes():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM nodes ORDER BY id")]

def get_node(node_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return dict(r) if r else None

def update_node(node_id, **kwargs):
    allowed = {"name", "address", "username", "password", "proxy_url", "enabled"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE nodes SET {sets} WHERE id=?", (*fields.values(), node_id))

def delete_node(node_id):
    with _conn() as c:
        c.execute("DELETE FROM nodes WHERE id=?", (node_id,))

def add_node_inbound(node_id, inbound_id, name=None, traffic_multiplier=1.0):
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO node_inbounds (node_id, inbound_id, name, traffic_multiplier) VALUES (?,?,?,?)",
            (node_id, inbound_id, name, max(1.0, float(traffic_multiplier)))
        )
        return cur.lastrowid

def get_node_inbounds(node_id):
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM node_inbounds WHERE node_id=? ORDER BY id", (node_id,))]

def get_node_inbound(ni_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM node_inbounds WHERE id=?", (ni_id,)).fetchone()
        return dict(r) if r else None

def get_node_inbound_with_node(ni_id):
    with _conn() as c:
        r = c.execute(
            "SELECT ni.id, ni.node_id, ni.inbound_id, ni.name AS inbound_name, ni.traffic_multiplier, ni.enabled AS inbound_enabled, "
            "n.name, n.address, n.username, n.password, n.proxy_url, n.enabled "
            "FROM node_inbounds ni JOIN nodes n ON ni.node_id=n.id WHERE ni.id=?",
            (ni_id,)
        ).fetchone()
        return dict(r) if r else None

def get_all_node_inbounds():
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT ni.*, n.name AS node_name, n.address, n.enabled AS node_enabled "
            "FROM node_inbounds ni JOIN nodes n ON ni.node_id=n.id ORDER BY ni.id"
        )]

def update_node_inbound(ni_id, **kwargs):
    allowed = {"inbound_id", "name", "traffic_multiplier", "enabled"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE node_inbounds SET {sets} WHERE id=?", (*fields.values(), ni_id))

def delete_node_inbound(ni_id):
    with _conn() as c:
        c.execute("DELETE FROM node_inbounds WHERE id=?", (ni_id,))

def create_sub(comment=None, data_gb=0, days=0, ip_limit=0, sub_id=None, enabled=True, show_multiplier=1, expire_after_first_use_seconds=0):
    sub_id = sub_id or generate(size=20)
    expire_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat() if days > 0 and not expire_after_first_use_seconds else None
    with _conn() as c:
        c.execute(
            "INSERT INTO subscriptions (id, comment, data_gb, days, ip_limit, expire_at, enabled, show_multiplier, expire_after_first_use_seconds) VALUES (?,?,?,?,?,?,?,?,?)",
            (sub_id, comment, data_gb, days, ip_limit, expire_at, int(enabled), max(1, int(show_multiplier)), int(expire_after_first_use_seconds))
        )
    return sub_id

def get_subs(page=1, per_page=20, search=None):
    limit = per_page if per_page > 0 else -1
    offset = (page - 1) * per_page if per_page > 0 else 0
    with _conn() as c:
        if search:
            rows = c.execute(
                "SELECT * FROM subscriptions WHERE id LIKE ? OR comment LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (f"%{search}%", f"%{search}%", limit, offset)
            ).fetchall()
            total = c.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE id LIKE ? OR comment LIKE ?",
                (f"%{search}%", f"%{search}%")
            ).fetchone()[0]
        else:
            rows = c.execute(
                "SELECT * FROM subscriptions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            total = c.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
        return [dict(r) for r in rows], total

def get_sub(sub_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
        return dict(r) if r else None

def get_sub_by_comment(comment):
    with _conn() as c:
        r = c.execute("SELECT * FROM subscriptions WHERE comment=? OR id=?", (comment, comment)).fetchone()
        return dict(r) if r else None

def update_sub(sub_id, **kwargs):
    allowed = {"comment", "data_gb", "days", "ip_limit", "used_bytes", "expire_at", "enabled", "show_multiplier", "expire_after_first_use_seconds"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if "days" in kwargs and kwargs["days"] > 0 and "expire_at" not in kwargs and not fields.get("expire_after_first_use_seconds"):
        fields["expire_at"] = (datetime.now(timezone.utc) + timedelta(days=int(kwargs["days"]))).isoformat()
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE subscriptions SET {sets} WHERE id=?", (*fields.values(), sub_id))

def delete_sub(sub_id):
    with _conn() as c:
        c.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))

def add_sub_node(sub_id, node_id, client_uuid, email):
    with _conn() as c:
        cnt = c.execute("SELECT COUNT(*) FROM subscription_nodes WHERE sub_id=?", (sub_id,)).fetchone()[0]
        c.execute(
            'INSERT OR REPLACE INTO subscription_nodes (sub_id, node_id, client_uuid, email, "order") VALUES (?,?,?,?,?)',
            (sub_id, node_id, client_uuid, email, cnt)
        )

def get_sub_nodes(sub_id):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT sn.sub_id, sn.node_id, sn.client_uuid, sn.email, sn.client_disabled, "
            "ni.inbound_id, ni.name AS inbound_name, ni.traffic_multiplier, "
            "n.name, n.address, n.username, n.password, n.proxy_url, n.enabled "
            "FROM subscription_nodes sn "
            "JOIN node_inbounds ni ON sn.node_id=ni.id "
            "JOIN nodes n ON ni.node_id=n.id "
            'WHERE sn.sub_id=? ORDER BY sn."order", sn.node_id', (sub_id,)
        )]

def get_all_sub_nodes():
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT sn.sub_id, sn.node_id, sn.client_uuid, sn.email, sn.client_disabled, "
            "ni.inbound_id, ni.name AS inbound_name, ni.traffic_multiplier, "
            "n.name, n.address, n.username, n.password, n.proxy_url, n.enabled "
            "FROM subscription_nodes sn "
            "JOIN node_inbounds ni ON sn.node_id=ni.id "
            "JOIN nodes n ON ni.node_id=n.id "
            'WHERE ni.enabled=1 AND n.enabled=1 ORDER BY sn."order", sn.node_id'
        )]

def remove_sub_node(sub_id, node_id):
    with _conn() as c:
        c.execute("DELETE FROM subscription_nodes WHERE sub_id=? AND node_id=?", (sub_id, node_id))

def set_sub_node_disabled(sub_id, node_id, disabled):
    with _conn() as c:
        c.execute("UPDATE subscription_nodes SET client_disabled=? WHERE sub_id=? AND node_id=?", (int(disabled), sub_id, node_id))

def reset_sub_node_disabled(sub_id):
    with _conn() as c:
        c.execute("UPDATE subscription_nodes SET client_disabled=0 WHERE sub_id=?", (sub_id,))

def reorder_sub_nodes(sub_id, node_ids):
    with _conn() as c:
        for i, nid in enumerate(node_ids):
            c.execute('UPDATE subscription_nodes SET "order"=? WHERE sub_id=? AND node_id=?', (i, sub_id, nid))

def log_access(sub_id, ip_address=None, user_agent=None):
    with _conn() as c:
        c.execute("INSERT INTO access_logs (sub_id, ip_address, user_agent) VALUES (?,?,?)", (sub_id, ip_address, user_agent))

def get_stats(sub_id):
    with _conn() as c:
        sub = c.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
        if not sub:
            return None
        count = c.execute("SELECT COUNT(*) FROM access_logs WHERE sub_id=?", (sub_id,)).fetchone()[0]
        first = c.execute("SELECT MIN(accessed_at) FROM access_logs WHERE sub_id=?", (sub_id,)).fetchone()[0]
        last_row = c.execute("SELECT accessed_at, user_agent FROM access_logs WHERE sub_id=? ORDER BY accessed_at DESC LIMIT 1", (sub_id,)).fetchone()
        last = last_row[0] if last_row else None
        last_ua = last_row[1] if last_row else None
        nodes = c.execute(
            "SELECT ni.name FROM subscription_nodes sn JOIN node_inbounds ni ON sn.node_id=ni.id WHERE sn.sub_id=?", (sub_id,)
        ).fetchall()
        return {**dict(sub), "access_count": count, "first_access": first, "last_access": last, "last_ua": last_ua, "nodes": [r[0] for r in nodes]}

def get_overview_stats():
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
        now = datetime.now(timezone.utc).isoformat()
        active = c.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE (expire_at IS NULL OR expire_at > ?) AND (data_gb=0 OR used_bytes < data_gb*1073741824)",
            (now,)
        ).fetchone()[0]
        nodes = c.execute(
            "SELECT COUNT(*) FROM node_inbounds ni JOIN nodes n ON ni.node_id=n.id WHERE ni.enabled=1 AND n.enabled=1"
        ).fetchone()[0]
        recent = c.execute("SELECT sub_id, accessed_at FROM access_logs ORDER BY accessed_at DESC LIMIT 10").fetchall()
        return {"total_subs": total, "active_subs": active, "nodes": nodes, "recent": [dict(r) for r in recent]}

def get_subs_pending_first_use_expiry():
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM subscriptions WHERE expire_after_first_use_seconds > 0 AND expire_at IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]
