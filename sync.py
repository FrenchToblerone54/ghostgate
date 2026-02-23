import threading
import time
import logging
from datetime import datetime, timezone
import database as db
from xui_client import XUIClient

logger = logging.getLogger("sync")

def _sync_once():
    subs, _ = db.get_subs(page=1, per_page=100000)
    all_snodes = db.get_all_sub_nodes()
    nodes_by_sub = {}
    for sn in all_snodes:
        nodes_by_sub.setdefault(sn["sub_id"], []).append(sn)
    for sub in subs:
        sid = sub["id"]
        snodes = nodes_by_sub.get(sid, [])
        if not snodes:
            continue
        total_bytes = 0
        for sn in snodes:
            try:
                xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                t = xui.get_client_traffic(sn["email"])
                if t:
                    total_bytes += (t.get("up") or 0) + (t.get("down") or 0)
            except Exception as e:
                logger.warning(f"sync error node {sn['node_id']} sub {sid}: {e}")
        db.update_sub(sid, used_bytes=total_bytes)
        limit_bytes = int(sub["data_gb"] * 1073741824) if sub["data_gb"] > 0 else 0
        now = datetime.now(timezone.utc)
        is_expired = bool(sub.get("expire_at")) and datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc) < now
        is_over_limit = limit_bytes > 0 and total_bytes >= limit_bytes
        if is_expired or is_over_limit:
            for sn in snodes:
                try:
                    xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                    xui.set_client_enabled(sn["inbound_id"], sn["client_uuid"], sn["email"], False)
                except Exception as e:
                    logger.warning(f"disable error node {sn['node_id']} sub {sid}: {e}")

def start_sync(interval=20):
    def _loop():
        while True:
            try:
                _sync_once()
            except Exception as e:
                logger.error(f"sync loop error: {e}")
            time.sleep(interval)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t
