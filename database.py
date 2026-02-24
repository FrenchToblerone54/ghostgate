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

def init_db():
    with _conn() as c:
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
    enabled INTEGER DEFAULT 1,
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
    ip_address TEXT,
    user_agent TEXT,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sub_id) REFERENCES subscriptions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_al_sub ON access_logs(sub_id);
        """)
        try:
            c.execute("ALTER TABLE subscriptions ADD COLUMN enabled INTEGER DEFAULT 1")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE access_logs ADD COLUMN ip_address TEXT")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE access_logs ADD COLUMN user_agent TEXT")
        except Exception:
            pass

def add_node(name, address, username, password, inbound_id, proxy_url=None):
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO nodes (name, address, username, password, inbound_id, proxy_url) VALUES (?,?,?,?,?,?)",
            (name, address, username, password, inbound_id, proxy_url)
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
    allowed = {"name", "address", "username", "password", "inbound_id", "proxy_url", "enabled"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE nodes SET {sets} WHERE id=?", (*fields.values(), node_id))

def delete_node(node_id):
    with _conn() as c:
        c.execute("DELETE FROM nodes WHERE id=?", (node_id,))

def create_sub(comment=None, data_gb=0, days=0, ip_limit=0, sub_id=None, enabled=True):
    sub_id = sub_id or generate(size=20)
    expire_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat() if days > 0 else None
    with _conn() as c:
        c.execute(
            "INSERT INTO subscriptions (id, comment, data_gb, days, ip_limit, expire_at, enabled) VALUES (?,?,?,?,?,?,?)",
            (sub_id, comment, data_gb, days, ip_limit, expire_at, int(enabled))
        )
    return sub_id

def get_subs(page=1, per_page=20, search=None):
    offset = (page - 1) * per_page
    with _conn() as c:
        if search:
            rows = c.execute(
                "SELECT * FROM subscriptions WHERE id LIKE ? OR comment LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (f"%{search}%", f"%{search}%", per_page, offset)
            ).fetchall()
            total = c.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE id LIKE ? OR comment LIKE ?",
                (f"%{search}%", f"%{search}%")
            ).fetchone()[0]
        else:
            rows = c.execute(
                "SELECT * FROM subscriptions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (per_page, offset)
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
    allowed = {"comment", "data_gb", "days", "ip_limit", "used_bytes", "expire_at", "enabled"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if "days" in kwargs and kwargs["days"] > 0 and "expire_at" not in kwargs:
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
        c.execute(
            "INSERT OR REPLACE INTO subscription_nodes (sub_id, node_id, client_uuid, email) VALUES (?,?,?,?)",
            (sub_id, node_id, client_uuid, email)
        )

def get_sub_nodes(sub_id):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT sn.*, n.name, n.address, n.username, n.password, n.inbound_id, n.proxy_url "
            "FROM subscription_nodes sn JOIN nodes n ON sn.node_id=n.id WHERE sn.sub_id=?", (sub_id,)
        )]

def get_all_sub_nodes():
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT sn.*, n.name, n.address, n.username, n.password, n.inbound_id, n.proxy_url, n.enabled "
            "FROM subscription_nodes sn JOIN nodes n ON sn.node_id=n.id WHERE n.enabled=1"
        )]

def remove_sub_node(sub_id, node_id):
    with _conn() as c:
        c.execute("DELETE FROM subscription_nodes WHERE sub_id=? AND node_id=?", (sub_id, node_id))

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
            "SELECT n.name FROM subscription_nodes sn JOIN nodes n ON sn.node_id=n.id WHERE sn.sub_id=?", (sub_id,)
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
        nodes = c.execute("SELECT COUNT(*) FROM nodes WHERE enabled=1").fetchone()[0]
        recent = c.execute("SELECT sub_id, accessed_at FROM access_logs ORDER BY accessed_at DESC LIMIT 10").fetchall()
        return {"total_subs": total, "active_subs": active, "nodes": nodes, "recent": [dict(r) for r in recent]}
