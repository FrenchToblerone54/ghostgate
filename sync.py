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
        xui_clients = {}
        node_bytes = {}
        total_effective = 0
        for sn in snodes:
            try:
                xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                xui_clients[sn["node_id"]] = xui
                t = xui.get_client_traffic(sn["email"])
                if t:
                    raw = (t.get("up") or 0) + (t.get("down") or 0)
                    node_bytes[sn["node_id"]] = raw
                    total_effective += raw * (sn.get("traffic_multiplier") or 1.0)
            except Exception as e:
                logger.warning(f"sync error node {sn['node_id']} sub {sid}: {e}")
        total_effective = int(total_effective)
        db.update_sub(sid, used_bytes=total_effective)
        limit_bytes = int(sub["data_gb"] * 1073741824) if sub["data_gb"] > 0 else 0
        now = datetime.now(timezone.utc)
        is_expired = bool(sub.get("expire_at")) and datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc) < now
        is_over_limit = limit_bytes > 0 and total_effective >= limit_bytes
        if sub.get("enabled") == 0:
            pass
        elif is_expired or is_over_limit:
            for sn in snodes:
                if sn.get("client_disabled"):
                    continue
                xui = xui_clients.get(sn["node_id"])
                if not xui:
                    continue
                try:
                    xui.set_client_enabled(sn["inbound_id"], sn["client_uuid"], sn["email"], False)
                    db.set_sub_node_disabled(sid, sn["node_id"], True)
                except Exception as e:
                    logger.warning(f"disable error node {sn['node_id']} sub {sid}: {e}")
        else:
            remaining = max(0, limit_bytes - total_effective) if limit_bytes > 0 else 0
            for sn in snodes:
                xui = xui_clients.get(sn["node_id"])
                if not xui:
                    continue
                if sn.get("client_disabled"):
                    try:
                        xui.set_client_enabled(sn["inbound_id"], sn["client_uuid"], sn["email"], True)
                        db.set_sub_node_disabled(sid, sn["node_id"], False)
                    except Exception as e:
                        logger.warning(f"re-enable error node {sn['node_id']} sub {sid}: {e}")
                if limit_bytes > 0:
                    mult = sn.get("traffic_multiplier") or 1.0
                    node_limit = int(node_bytes.get(sn["node_id"], 0) + remaining / mult)
                    try:
                        xui.update_client_limit(sn["inbound_id"], sn["client_uuid"], sn["email"], node_limit)
                    except Exception as e:
                        logger.warning(f"limit update error node {sn['node_id']} sub {sid}: {e}")

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
