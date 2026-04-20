import os
import threading
import time
import logging
import uuid
from datetime import datetime, timezone
import database as db
from xui_client import XUIClient

logger = logging.getLogger("sync")

def _ghostgate_restart_enabled():
    return os.getenv("GHOSTGATE_RESTART_OVERLIMIT_EXPIRED", "false").lower() == "true"

def _tmult(sn):
    v = sn.get("traffic_multiplier")
    return 1.0 if v is None else float(v)

def _sub_expiry_time(sub):
    expire_ms = 0
    if sub.get("expire_at"):
        try:
            expire_ms = int(datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except Exception:
            pass
    expire_after = int(sub.get("expire_after_first_use_seconds") or 0)
    return -expire_after*1000 if expire_after>0 and not sub.get("expire_at") else expire_ms

def _sync_once():
    subs, _ = db.get_subs(page=1, per_page=100000)
    all_snodes = db.get_all_sub_nodes()
    nodes_by_sub = {}
    for sn in all_snodes:
        nodes_by_sub.setdefault(sn["sub_id"], []).append(sn)
    _xui_sessions = {}
    _xui_failed = set()
    restart_keys = set()
    for sub in subs:
        sid = sub["id"]
        snodes = nodes_by_sub.get(sid, [])
        if not snodes:
            continue
        xui_clients = {}
        node_bytes = {}
        total_effective = 0
        for sn in snodes:
            key = (sn["address"], sn["username"])
            if key in _xui_failed:
                continue
            try:
                if key not in _xui_sessions:
                    _xui_sessions[key] = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                xui = _xui_sessions[key]
                xui_clients[sn["node_id"]] = xui
                t = xui.get_client_traffic(sn["email"])
                if t:
                    raw = (t.get("up") or 0) + (t.get("down") or 0)
                    node_bytes[sn["node_id"]] = raw
                    offset = sn.get("traffic_offset") or 0.0
                    baseline = sn.get("traffic_baseline") or 0
                    adjusted_raw = max(0, raw - baseline)
                    total_effective += offset + adjusted_raw * _tmult(sn)
            except Exception as e:
                _xui_failed.add(key)
                logger.warning(f"sync error node {sn['node_id']} sub {sid}: {e}")
        total_effective += float(sub.get("traffic_preserved") or 0)
        total_effective = int(total_effective)
        prev_used = sub.get("used_bytes") or 0
        traffic_changed = total_effective != prev_used
        if traffic_changed:
            db.update_sub(sid, used_bytes=total_effective)
        limit_bytes = int(sub["data_gb"] * 1073741824) if sub["data_gb"] > 0 else 0
        now = datetime.now(timezone.utc)
        is_expired = bool(sub.get("expire_at")) and datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc) < now
        is_over_limit = limit_bytes > 0 and total_effective >= limit_bytes
        if sub.get("enabled") == 0:
            pass
        elif is_expired or is_over_limit:
            new_uuid = str(uuid.uuid4())
            for sn in snodes:
                if sn.get("client_disabled"):
                    continue
                xui = xui_clients.get(sn["node_id"])
                if not xui:
                    continue
                try:
                    ok = xui.rotate_client_uuid(sn["inbound_id"], sn["client_uuid"], sn["email"], new_uuid, enabled=False)
                    if ok:
                        db.update_sub_node_uuid(sid, sn["node_id"], new_uuid)
                        db.set_sub_node_disabled(sid, sn["node_id"], True)
                        if _ghostgate_restart_enabled():
                            restart_keys.add((sn["address"], sn["username"]))
                    else:
                        ok2 = xui.set_client_enabled(sn["inbound_id"], sn["client_uuid"], sn["email"], False)
                        if ok2:
                            db.set_sub_node_disabled(sid, sn["node_id"], True)
                            if _ghostgate_restart_enabled():
                                restart_keys.add((sn["address"], sn["username"]))
                except Exception as e:
                    logger.warning(f"disable error node {sn['node_id']} sub {sid}: {e}")
        else:
            remaining = max(0, limit_bytes - total_effective) if limit_bytes > 0 else 0
            expiry_time = _sub_expiry_time(sub)
            ip_limit = sub.get("ip_limit", 0)
            for sn in snodes:
                xui = xui_clients.get(sn["node_id"])
                if not xui:
                    continue
                mult = _tmult(sn)
                node_limit = int(node_bytes.get(sn["node_id"], 0) + remaining / mult) if limit_bytes > 0 and mult > 0 else 0
                if sn.get("client_disabled"):
                    try:
                        ok = xui.sync_client(sn["inbound_id"], sn["client_uuid"], sn["email"], enabled=True, expire_ms=expiry_time, ip_limit=ip_limit, total_limit_bytes=node_limit)
                        if ok:
                            db.set_sub_node_disabled(sid, sn["node_id"], False)
                    except Exception as e:
                        logger.warning(f"re-enable error node {sn['node_id']} sub {sid}: {e}")
                if limit_bytes > 0 and traffic_changed:
                    try:
                        xui.update_client_limit(sn["inbound_id"], sn["client_uuid"], sn["email"], node_limit)
                    except Exception as e:
                        logger.warning(f"limit update error node {sn['node_id']} sub {sid}: {e}")
    if restart_keys:
        for key in restart_keys:
            xui = _xui_sessions.get(key)
            if not xui:
                continue
            try:
                if xui.restart_xray():
                    logger.info(f"GhostGate restarted Xray on {key[0]}")
                else:
                    logger.warning(f"GhostGate failed to restart Xray on {key[0]}")
            except Exception as e:
                logger.warning(f"GhostGate restart error on {key[0]}: {e}")

def _sync_first_use_expiry():
    subs = db.get_subs_pending_first_use_expiry()
    _xui_sessions = {}
    _xui_failed = set()
    for sub in subs:
        sid = sub["id"]
        seconds = sub.get("expire_after_first_use_seconds", 0)
        if seconds <= 0:
            continue
        snodes = db.get_sub_nodes(sid)
        earliest_expiry_ms = None
        has_any_expiry = False
        for sn in snodes:
            key = (sn["address"], sn["username"])
            if key in _xui_failed:
                continue
            try:
                if key not in _xui_sessions:
                    _xui_sessions[key] = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                xui = _xui_sessions[key]
                client = xui.get_client_by_email(sn["inbound_id"], sn["email"])
                if client:
                    expiry_ms = client.get("expiryTime", 0)
                    if expiry_ms != 0:
                        has_any_expiry = True
                    if expiry_ms > 0:
                        if earliest_expiry_ms is None or expiry_ms < earliest_expiry_ms:
                            earliest_expiry_ms = expiry_ms
            except Exception as e:
                _xui_failed.add(key)
                logger.warning(f"first-use expiry check error node {sn['node_id']} sub {sid}: {e}")
        if not has_any_expiry:
            expire_ms = -seconds * 1000
            ip_limit = sub.get("ip_limit", 0)
            for sn in snodes:
                key = (sn["address"], sn["username"])
                if key in _xui_failed:
                    continue
                try:
                    if key not in _xui_sessions:
                        _xui_sessions[key] = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                    _xui_sessions[key].update_client_expiry_ip(sn["inbound_id"], sn["client_uuid"], sn["email"], expire_ms, ip_limit)
                    logger.info(f"Set initial negative expiry on node {sn['node_id']} for sub {sid}: {expire_ms}")
                except Exception as e:
                    _xui_failed.add(key)
                    logger.warning(f"set initial expiry error node {sn['node_id']} sub {sid}: {e}")
        elif earliest_expiry_ms:
            expire_at = datetime.fromtimestamp(earliest_expiry_ms / 1000, tz=timezone.utc).isoformat()
            db.update_sub(sid, expire_at=expire_at)
            logger.info(f"Set expire_at for sub {sid} based on first use: {expire_at}")
            expire_ms = int(earliest_expiry_ms)
            ip_limit = sub.get("ip_limit", 0)
            for sn in snodes:
                key = (sn["address"], sn["username"])
                if key in _xui_failed:
                    continue
                try:
                    if key not in _xui_sessions:
                        _xui_sessions[key] = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                    _xui_sessions[key].update_client_expiry_ip(sn["inbound_id"], sn["client_uuid"], sn["email"], expire_ms, ip_limit)
                except Exception as e:
                    _xui_failed.add(key)
                    logger.warning(f"sync expiry to node {sn['node_id']} sub {sid}: {e}")

def start_sync(interval=20):
    def _loop():
        while True:
            try:
                _sync_once()
                _sync_first_use_expiry()
            except Exception as e:
                logger.error(f"sync loop error: {e}")
            time.sleep(interval)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t
