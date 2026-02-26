import os
import sys
import json
import uuid
import base64
import io
import time
import threading
import subprocess
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, Response, render_template_string, abort
import psutil
import qrcode
from dotenv import dotenv_values, set_key
import database as db
import updater
from xui_client import XUIClient

app = Flask(__name__)
BASE_URL = ""

def _sys_info():
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    load = psutil.getloadavg()
    return {
        "cpu_percent": cpu, "cpu_count": psutil.cpu_count(),
        "ram_percent": ram.percent, "ram_used": ram.used // 1048576, "ram_total": ram.total // 1048576,
        "swap_percent": swap.percent, "swap_used": swap.used // 1048576, "swap_total": swap.total // 1048576,
        "disk_percent": disk.percent, "disk_used": round(disk.used / 1073741824, 2), "disk_total": round(disk.total / 1073741824, 2),
        "net_sent": net.bytes_sent, "net_recv": net.bytes_recv,
        "load_1": round(load[0], 2), "load_5": round(load[1], 2), "load_15": round(load[2], 2)
    }

def _fmt_vless(client_uuid, label, server, port, stream_settings, security):
    params = {"type": stream_settings.get("network", "tcp"), "security": security}
    network = stream_settings.get("network", "tcp")
    tcp_s = stream_settings.get("tcpSettings", {})
    ws_s = stream_settings.get("wsSettings", {})
    grpc_s = stream_settings.get("grpcSettings", {})
    kcp_s = stream_settings.get("kcpSettings", {})
    hu_s = stream_settings.get("httpupgradeSettings", {})
    xhttp_s = stream_settings.get("xhttpSettings", {})
    tls_s = stream_settings.get("tlsSettings", {})
    reality_s = stream_settings.get("realitySettings", {})
    if network == "tcp":
        htype = tcp_s.get("header", {}).get("type", "none")
        if htype != "none":
            params["headerType"] = htype
        paths = tcp_s.get("header", {}).get("request", {}).get("path", [])
        if paths:
            params["path"] = paths[0]
        hosts = tcp_s.get("header", {}).get("request", {}).get("headers", {}).get("Host", [""])
        if hosts and hosts[0]:
            params["host"] = hosts[0]
    elif network == "ws":
        params["path"] = ws_s.get("path", "/")
        host = ws_s.get("headers", {}).get("Host", "")
        if host:
            params["host"] = host
    elif network == "grpc":
        params["serviceName"] = grpc_s.get("serviceName", "")
        params["mode"] = "multi"
    elif network == "kcp":
        params["headerType"] = kcp_s.get("header", {}).get("type", "none")
        seed = kcp_s.get("seed", "")
        if seed:
            params["seed"] = seed
    elif network in ("httpupgrade", "xhttp"):
        s = hu_s if network == "httpupgrade" else xhttp_s
        params["path"] = s.get("path", "/")
        host = s.get("host", "")
        if host:
            params["host"] = host
        if network == "xhttp":
            params["mode"] = s.get("mode", "auto")
    if security == "tls":
        fp = tls_s.get("fingerprint", "")
        if fp:
            params["fp"] = fp
        alpn = tls_s.get("alpn", [])
        if alpn:
            params["alpn"] = ",".join(alpn)
        sni = tls_s.get("serverName", "")
        if sni:
            params["sni"] = sni
        if tls_s.get("allowInsecure", False):
            params["allowInsecure"] = "1"
    elif security == "reality":
        params["pbk"] = reality_s.get("publicKey", "")
        fp = reality_s.get("fingerprint", "")
        if fp:
            params["fp"] = fp
        sni = (reality_s.get("serverNames") or [""])[0]
        if sni:
            params["sni"] = sni
        sid = (reality_s.get("shortIds") or [""])[0]
        if sid:
            params["sid"] = sid
        spx = reality_s.get("spiderX", "")
        if spx:
            params["spx"] = quote(spx)
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return f"vless://{client_uuid}@{server}:{port}?{query}#{quote(label)}"

def _make_qr_b64(text):
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#00e5a0", back_color="#1a1d2e")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

@app.route("/sub/<sub_id>")
def sub_page(sub_id):
    sub = db.get_sub(sub_id)
    if not sub:
        return abort(404)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    ua = request.headers.get("User-Agent", "")
    db.log_access(sub_id, ip, ua)
    snodes = db.get_sub_nodes(sub_id)
    base_url = BASE_URL or request.host_url.rstrip("/")
    sub_url = f"{base_url}/sub/{sub_id}"
    sm = max(1, int(sub.get("show_multiplier") or 1))
    total_bytes = sub.get("used_bytes") or 0
    limit_bytes = int(sub["data_gb"] * 1073741824) if sub["data_gb"] > 0 else 0
    expire_ts = 0
    if sub.get("expire_at"):
        try:
            expire_ts = int(datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            pass
    now_ts = int(datetime.now(timezone.utc).timestamp())
    is_expired = expire_ts > 0 and expire_ts < now_ts
    is_over_limit = limit_bytes > 0 and total_bytes >= limit_bytes
    data_percent = min(100, int(total_bytes * 100 / limit_bytes)) if limit_bytes > 0 else 0
    data_used_str = f"{total_bytes*sm/1073741824:.2f} GB"
    data_total_str = f"{sub['data_gb']*sm:.1f} GB" if limit_bytes > 0 else "Unlimited"
    if expire_ts > 0:
        diff = expire_ts - now_ts
        expire_str = f"{diff // 86400}d {(diff % 86400) // 3600}h" if diff > 0 else "Expired"
    else:
        expire_str = "No Expiry"
    data_label = os.getenv("DATA_LABEL", "⬇️ Data left")
    expire_label = os.getenv("EXPIRE_LABEL", "⏰ Expires")
    is_browser = any(b in ua for b in ["Mozilla", "Chrome", "Safari", "Firefox", "Edge", "Opera"])
    if is_browser:
        qr_b64 = _make_qr_b64(sub_url)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base_dir, "frontend", "sub.html")) as f:
            tmpl = f.read()
        sub_enabled = bool(sub.get("enabled", 1))
        return render_template_string(tmpl,
            sub_url=sub_url, qr_b64=qr_b64,
            data_used_str=data_used_str, data_total_str=data_total_str, data_percent=data_percent,
            expire_str=expire_str, is_expired=is_expired, is_over_limit=is_over_limit,
            sub_enabled=sub_enabled,
            data_label=data_label, expire_label=expire_label
        )
    configs = [
        f"vless://00000000-0000-0000-0000-000000000001@0.0.0.0:443?type=tcp#{quote(f'{data_label}: {total_bytes*sm/1073741824:.2f} GB / {data_total_str}')}",
        f"vless://00000000-0000-0000-0000-000000000002@0.0.0.0:443?type=tcp#{quote(f'{expire_label}: {expire_str}')}",
    ]
    for sn in snodes:
        try:
            xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
            inbound = xui.get_inbound(sn["inbound_id"])
            if not inbound:
                continue
            stream = json.loads(inbound.get("streamSettings", "{}"))
            orig_security = stream.get("security", "none")
            orig_port = inbound.get("port", 443)
            raw_addr = sn["address"].split("//")[-1].split("/")[0]
            orig_server = raw_addr.split(":")[0]
            ext_proxies = stream.get("externalProxy") or []
            if ext_proxies:
                for i, ep in enumerate(ext_proxies):
                    ep_server = ep.get("dest", orig_server)
                    ep_port = ep.get("port", orig_port)
                    force_tls = ep.get("forceTls", "same")
                    ep_security = orig_security if force_tls == "same" else force_tls
                    ep_stream = dict(stream)
                    ep_stream["security"] = ep_security
                    label = f"{sn['name']}-{i+1}" if i > 0 else sn["name"]
                    configs.append(_fmt_vless(sn["client_uuid"], label, ep_server, ep_port, ep_stream, ep_security))
            else:
                configs.append(_fmt_vless(sn["client_uuid"], sn["name"], orig_server, orig_port, stream, orig_security))
        except Exception:
            pass
    profile_title = os.getenv("PROFILE_TITLE", "GhostGate Subscription")
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Profile-Title": base64.b64encode(profile_title.encode()).decode(),
        "subscription-userinfo": f"upload=0;download={total_bytes*sm};total={limit_bytes*sm if limit_bytes else 0};expire={expire_ts}",
        "profile-update-interval": "1",
        "Content-Disposition": "attachment; filename=ghostgate",
        "profile-web-page-url": sub_url
    }
    return "\n".join(configs), 200, headers

def register_routes(panel_path):
    global BASE_URL
    BASE_URL = os.getenv("BASE_URL", "")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base_dir, "frontend", "index.html")) as f:
        _panel_html = f.read().replace("{{prefix}}", f"/{panel_path}").replace("{{version}}", updater.VERSION)
    _err_pages = {}
    for code in [400, 403, 404, 405, 500]:
        fp = os.path.join(base_dir, "frontend", f"{code}.html")
        try:
            with open(fp) as f:
                _err_pages[code] = f.read()
        except Exception:
            _err_pages[code] = ""

    @app.route(f"/{panel_path}/", strict_slashes=False)
    def panel_index():
        return _panel_html

    @app.route(f"/{panel_path}/api/status")
    def api_status():
        stats = db.get_overview_stats()
        sys_info = _sys_info()
        return jsonify({**stats, "system": sys_info})

    @app.route(f"/{panel_path}/api/stream")
    def api_stream():
        def _gen():
            while True:
                try:
                    stats = db.get_overview_stats()
                    sys_info = _sys_info()
                    yield f"data: {json.dumps({**stats, 'system': sys_info})}\n\n"
                except Exception:
                    pass
                time.sleep(3)
        return Response(_gen(), content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.route(f"/{panel_path}/api/subscriptions")
    def api_subs_list():
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        search = request.args.get("search", "").strip() or None
        subs, total = db.get_subs(page, per_page, search)
        for sub in subs:
            sub["node_names"] = [sn.get("inbound_name") or sn["name"] for sn in db.get_sub_nodes(sub["id"])]
        return jsonify({"subs": subs, "total": total, "page": page, "per_page": per_page})

    @app.route(f"/{panel_path}/api/subscriptions/stream")
    def api_subs_stream():
        def _gen():
            prev = {}
            first = True
            while True:
                try:
                    subs, _ = db.get_subs(1, 0)
                    for sub in subs:
                        sub["node_names"] = [sn.get("inbound_name") or sn["name"] for sn in db.get_sub_nodes(sub["id"])]
                    curr = {s["id"]: s for s in subs}
                    changed = False
                    if not first:
                        for sid in set(prev.keys()) - set(curr.keys()):
                            yield f"data: {json.dumps({'type': 'delete', 'id': sid})}\n\n"
                            changed = True
                        for sid, sub in curr.items():
                            h = json.dumps({k: sub.get(k) for k in ["used_bytes", "expire_at", "enabled", "data_gb", "comment", "node_names", "ip_limit", "expire_after_first_use_seconds"]}, sort_keys=True)
                            if prev.get(sid) != h:
                                yield f"data: {json.dumps({'type': 'update', 'sub': sub})}\n\n"
                                changed = True
                        if not changed:
                            yield ": heartbeat\n\n"
                    first = False
                    prev = {sid: json.dumps({k: curr[sid].get(k) for k in ["used_bytes", "expire_at", "enabled", "data_gb", "comment", "node_names", "ip_limit", "expire_after_first_use_seconds"]}, sort_keys=True) for sid in curr}
                except Exception:
                    pass
                time.sleep(5)
        return Response(_gen(), content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.route(f"/{panel_path}/api/subscriptions", methods=["POST"])
    def api_subs_create():
        data = request.json
        comment = data.get("comment")
        data_gb = float(data.get("data_gb", 0))
        days = int(data.get("days", 0))
        ip_limit = int(data.get("ip_limit", 0))
        show_multiplier = max(1, int(data.get("show_multiplier", 1)))
        expire_after_first_use_seconds = int(data.get("expire_after_first_use_seconds", 0))
        node_ids = [int(n) for n in data.get("node_ids", [])]
        sub_id = db.create_sub(comment=comment, data_gb=data_gb, days=days, ip_limit=ip_limit, show_multiplier=show_multiplier, expire_after_first_use_seconds=expire_after_first_use_seconds)
        sub = db.get_sub(sub_id)
        client_uuid = str(uuid.uuid4())
        expire_ms = 0
        if sub.get("expire_at"):
            try:
                expire_ms = int(datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
            except Exception:
                pass
        expire_after = int(sub.get("expire_after_first_use_seconds") or 0)
        expiry_time = -expire_after if expire_after>0 and not sub.get("expire_at") else expire_ms
        errors = []
        for node_id in node_ids:
            ni = db.get_node_inbound_with_node(node_id)
            if not ni:
                continue
            try:
                xui = XUIClient(ni["address"], ni["username"], ni["password"], ni.get("proxy_url"))
                total_limit_bytes = int(max(0, data_gb * 1073741824 - (sub.get("used_bytes") or 0)) / (ni.get("traffic_multiplier") or 1.0)) if data_gb > 0 else 0
                email = f"{sub_id}-{node_id}"
                expiry_time = -expire_after_first_use_seconds*1000 if expire_after_first_use_seconds>0 else expire_ms
                client = xui.make_client(email, client_uuid, expiry_time, ip_limit, sub_id, comment or "", total_limit_bytes)
                ok = xui.add_client(ni["inbound_id"], client)
                if ok:
                    db.add_sub_node(sub_id, node_id, client_uuid, email)
                else:
                    errors.append(f"inbound {node_id}: failed to add client")
            except Exception as e:
                errors.append(f"inbound {node_id}: {e}")
        base_url = BASE_URL or request.host_url.rstrip("/")
        return jsonify({"id": sub_id, "uuid": client_uuid, "url": f"{base_url}/sub/{sub_id}", "errors": errors})

    @app.route(f"/{panel_path}/api/subscriptions/<sub_id>")
    def api_sub_get(sub_id):
        sub = db.get_sub(sub_id)
        if not sub:
            return jsonify({"error": "not found"}), 404
        sub["nodes"] = db.get_sub_nodes(sub_id)
        return jsonify(sub)

    @app.route(f"/{panel_path}/api/subscriptions/<sub_id>", methods=["PUT"])
    def api_sub_update(sub_id):
        body = request.json
        updates = {k: body[k] for k in ["comment", "data_gb", "days", "ip_limit", "enabled", "show_multiplier", "expire_after_first_use_seconds"] if k in body}
        if body.get("remove_expiry"):
            updates["expire_at"] = None
        if "expire_after_first_use_seconds" in updates and int(updates.get("expire_after_first_use_seconds") or 0)>0:
            updates["expire_at"] = None
        elif "remove_days" in body and int(body["remove_days"]) > 0:
            sub = db.get_sub(sub_id)
            if sub and sub.get("expire_at"):
                try:
                    base = datetime.fromisoformat(sub["expire_at"])
                    if base.tzinfo is None:
                        base = base.replace(tzinfo=timezone.utc)
                    updates["expire_at"] = (base - timedelta(days=int(body["remove_days"]))).isoformat()
                except Exception:
                    pass
        if body.get("expire_at"):
            try:
                d = datetime.fromisoformat(body["expire_at"])
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                updates["expire_at"] = d.isoformat()
            except Exception:
                pass
        db.update_sub(sub_id, **updates)
        sub = db.get_sub(sub_id)
        snodes = db.get_sub_nodes(sub_id)
        if "enabled" in body:
            enabled_val = bool(body["enabled"])
            if enabled_val:
                db.reset_sub_node_disabled(sub_id)
            for sn in snodes:
                try:
                    xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                    xui.set_client_enabled(sn["inbound_id"], sn["client_uuid"], sn["email"], enabled_val)
                except Exception:
                    pass
        if any(k in updates for k in ("expire_at", "days", "ip_limit", "expire_after_first_use_seconds")) or body.get("remove_expiry") or "remove_days" in body:
            expire_ms = 0
            if sub and sub.get("expire_at"):
                try:
                    expire_ms = int(datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
                except Exception:
                    pass
            expire_after = int(sub.get("expire_after_first_use_seconds") or 0) if sub else 0
            expiry_time = -expire_after*1000 if expire_after>0 and not (sub and sub.get("expire_at")) else expire_ms
            ip_limit = sub.get("ip_limit", 0) if sub else 0
            for sn in snodes:
                try:
                    xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                    xui.update_client_expiry_ip(sn["inbound_id"], sn["client_uuid"], sn["email"], expiry_time, ip_limit)
                except Exception:
                    pass
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/subscriptions/<sub_id>", methods=["DELETE"])
    def api_sub_delete(sub_id):
        snodes = db.get_sub_nodes(sub_id)
        for sn in snodes:
            try:
                xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                xui.delete_client(sn["inbound_id"], sn["client_uuid"])
            except Exception:
                pass
        db.delete_sub(sub_id)
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/subscriptions/<sub_id>/nodes", methods=["POST"])
    def api_sub_add_nodes(sub_id):
        sub = db.get_sub(sub_id)
        if not sub:
            return jsonify({"error": "not found"}), 404
        node_ids = [int(n) for n in request.json.get("node_ids", [])]
        existing = {sn["node_id"] for sn in db.get_sub_nodes(sub_id)}
        expire_ms = 0
        if sub.get("expire_at"):
            try:
                expire_ms = int(datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
            except Exception:
                pass
        expire_after = int(sub.get("expire_after_first_use_seconds") or 0)
        expiry_time = -expire_after if expire_after>0 and not sub.get("expire_at") else expire_ms
        errors = []
        for node_id in node_ids:
            if node_id in existing:
                continue
            ni = db.get_node_inbound_with_node(node_id)
            if not ni:
                continue
            try:
                client_uuid = str(uuid.uuid4())
                xui = XUIClient(ni["address"], ni["username"], ni["password"], ni.get("proxy_url"))
                total_limit_bytes = int(max(0, sub["data_gb"] * 1073741824 - (sub.get("used_bytes") or 0)) / (ni.get("traffic_multiplier") or 1.0)) if sub["data_gb"] > 0 else 0
                email = f"{sub_id}-{node_id}"
                client = xui.make_client(email, client_uuid, expiry_time, sub.get("ip_limit", 0), sub_id, sub.get("comment") or "", total_limit_bytes)
                now = datetime.now(timezone.utc)
                is_disabled = sub.get("enabled") == 0
                is_expired = sub.get("expire_at") and datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc) < now
                is_over_limit = sub["data_gb"] > 0 and (sub.get("used_bytes") or 0) >= sub["data_gb"] * 1073741824
                if is_disabled or is_expired or is_over_limit:
                    client["enable"] = False
                ok = xui.add_client(ni["inbound_id"], client)
                if ok:
                    db.add_sub_node(sub_id, node_id, client_uuid, email)
                    if is_disabled or is_expired or is_over_limit:
                        db.set_sub_node_disabled(sub_id, node_id, True)
                else:
                    errors.append(f"inbound {node_id}: failed to add client")
            except Exception as e:
                errors.append(f"inbound {node_id}: {e}")
        return jsonify({"ok": True, "errors": errors})

    @app.route(f"/{panel_path}/api/subscriptions/<sub_id>/nodes/<int:node_id>", methods=["DELETE"])
    def api_sub_remove_node(sub_id, node_id):
        snodes = db.get_sub_nodes(sub_id)
        sn = next((s for s in snodes if s["node_id"] == node_id), None)
        if sn:
            try:
                xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                xui.delete_client(sn["inbound_id"], sn["client_uuid"])
            except Exception:
                pass
            db.remove_sub_node(sub_id, node_id)
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/bulk/nodes", methods=["POST"])
    def api_bulk_nodes():
        data = request.json
        sub_ids = data.get("sub_ids", [])
        node_ids = [int(n) for n in data.get("node_ids", [])]
        action = data.get("action")
        errors = []
        for sub_id in sub_ids:
            sub = db.get_sub(sub_id)
            if not sub:
                continue
            if action == "add":
                existing = {sn["node_id"] for sn in db.get_sub_nodes(sub_id)}
                expire_ms = 0
                if sub.get("expire_at"):
                    try:
                        expire_ms = int(datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
                    except Exception:
                        pass
                expire_after = int(sub.get("expire_after_first_use_seconds") or 0)
                expiry_time = -expire_after if expire_after>0 and not sub.get("expire_at") else expire_ms
                for node_id in node_ids:
                    if node_id in existing:
                        continue
                    ni = db.get_node_inbound_with_node(node_id)
                    if not ni:
                        continue
                    try:
                        client_uuid = str(uuid.uuid4())
                        xui = XUIClient(ni["address"], ni["username"], ni["password"], ni.get("proxy_url"))
                        total_limit_bytes = int(max(0, sub["data_gb"] * 1073741824 - (sub.get("used_bytes") or 0)) / (ni.get("traffic_multiplier") or 1.0)) if sub["data_gb"] > 0 else 0
                        email = f"{sub_id}-{node_id}"
                        client = xui.make_client(email, client_uuid, expiry_time, sub.get("ip_limit", 0), sub_id, sub.get("comment") or "", total_limit_bytes)
                        now = datetime.now(timezone.utc)
                        is_disabled = sub.get("enabled") == 0
                        is_expired = sub.get("expire_at") and datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc) < now
                        is_over_limit = sub["data_gb"] > 0 and (sub.get("used_bytes") or 0) >= sub["data_gb"] * 1073741824
                        if is_disabled or is_expired or is_over_limit:
                            client["enable"] = False
                        ok = xui.add_client(ni["inbound_id"], client)
                        if ok:
                            db.add_sub_node(sub_id, node_id, client_uuid, email)
                            if is_disabled or is_expired or is_over_limit:
                                db.set_sub_node_disabled(sub_id, node_id, True)
                        else:
                            errors.append(f"{sub_id}/inbound {node_id}: failed")
                    except Exception as e:
                        errors.append(f"{sub_id}/inbound {node_id}: {e}")
            elif action == "remove":
                snodes = db.get_sub_nodes(sub_id)
                for node_id in node_ids:
                    sn = next((s for s in snodes if s["node_id"] == node_id), None)
                    if not sn:
                        continue
                    try:
                        xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                        xui.delete_client(sn["inbound_id"], sn["client_uuid"])
                    except Exception:
                        pass
                    db.remove_sub_node(sub_id, node_id)
        return jsonify({"ok": True, "errors": errors})

    @app.route(f"/{panel_path}/api/bulk/extend", methods=["POST"])
    def api_bulk_extend():
        data = request.json
        sub_ids = data.get("sub_ids", [])
        add_data_gb = float(data.get("data_gb", 0))
        add_days = int(data.get("days", 0))
        remove_expiry = bool(data.get("remove_expiry", False))
        remove_data_limit = bool(data.get("remove_data_limit", False))
        for sub_id in sub_ids:
            sub = db.get_sub(sub_id)
            if not sub:
                continue
            updates = {}
            if remove_data_limit:
                updates["data_gb"] = 0
            elif add_data_gb != 0:
                updates["data_gb"] = max(0, (sub.get("data_gb") or 0) + add_data_gb)
            if remove_expiry:
                updates["expire_at"] = None
            elif add_days != 0:
                try:
                    base = datetime.fromisoformat(sub["expire_at"]) if sub.get("expire_at") else (datetime.now(timezone.utc) if add_days > 0 else None)
                    if base is not None:
                        if base.tzinfo is None:
                            base = base.replace(tzinfo=timezone.utc)
                        updates["expire_at"] = (base + timedelta(days=add_days)).isoformat()
                except Exception:
                    if add_days > 0:
                        updates["expire_at"] = (datetime.now(timezone.utc) + timedelta(days=add_days)).isoformat()
            if updates:
                db.update_sub(sub_id, **updates)
                if remove_expiry or add_days != 0:
                    updated_sub = db.get_sub(sub_id)
                    expire_ms = 0
                    if updated_sub and updated_sub.get("expire_at"):
                        try:
                            expire_ms = int(datetime.fromisoformat(updated_sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
                        except Exception:
                            pass
                    for sn in db.get_sub_nodes(sub_id):
                        try:
                            xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                            xui.update_client_expiry_ip(sn["inbound_id"], sn["client_uuid"], sn["email"], expire_ms, updated_sub.get("ip_limit", 0))
                        except Exception:
                            pass
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/bulk/delete", methods=["POST"])
    def api_bulk_delete():
        sub_ids = request.json.get("sub_ids", [])
        for sub_id in sub_ids:
            snodes = db.get_sub_nodes(sub_id)
            for sn in snodes:
                try:
                    xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                    xui.delete_client(sn["inbound_id"], sn["client_uuid"])
                except Exception:
                    pass
            db.delete_sub(sub_id)
        return jsonify({"ok": True, "deleted": len(sub_ids)})

    @app.route(f"/{panel_path}/api/bulk/toggle", methods=["POST"])
    def api_bulk_toggle():
        data = request.json
        sub_ids = data.get("sub_ids", [])
        enabled_val = bool(data.get("enabled", True))
        for sub_id in sub_ids:
            db.update_sub(sub_id, enabled=1 if enabled_val else 0)
            snodes = db.get_sub_nodes(sub_id)
            for sn in snodes:
                try:
                    xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                    xui.set_client_enabled(sn["inbound_id"], sn["client_uuid"], sn["email"], enabled_val)
                except Exception:
                    pass
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/subscriptions/<sub_id>/stats")
    def api_sub_stats(sub_id):
        return jsonify(db.get_stats(sub_id))

    @app.route(f"/{panel_path}/api/subscriptions/<sub_id>/qr")
    def api_sub_qr(sub_id):
        base_url = BASE_URL or request.host_url.rstrip("/")
        sub_url = f"{base_url}/sub/{sub_id}"
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(sub_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#00e5a0", back_color="#1a1d2e")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return Response(buf.read(), content_type="image/png")

    @app.route(f"/{panel_path}/api/nodes")
    def api_nodes_list():
        nodes = db.get_nodes()
        for n in nodes:
            n.pop("password", None)
            n["inbounds"] = db.get_node_inbounds(n["id"])
        return jsonify(nodes)

    @app.route(f"/{panel_path}/api/nodes", methods=["POST"])
    def api_nodes_create():
        data = request.json
        node_id = db.add_node(data["name"], data["address"], data["username"], data["password"], data.get("proxy_url"))
        return jsonify({"id": node_id})

    @app.route(f"/{panel_path}/api/nodes/<int:node_id>", methods=["PUT"])
    def api_node_update(node_id):
        data = request.json
        db.update_node(node_id, **data)
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/nodes/<int:node_id>", methods=["DELETE"])
    def api_node_delete(node_id):
        db.delete_node(node_id)
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/nodes/<int:node_id>/inbounds")
    def api_node_inbounds_list(node_id):
        return jsonify(db.get_node_inbounds(node_id))

    @app.route(f"/{panel_path}/api/nodes/<int:node_id>/inbounds", methods=["POST"])
    def api_node_inbound_create(node_id):
        data = request.json
        ni_id = db.add_node_inbound(node_id, int(data["inbound_id"]), data.get("name"), float(data.get("traffic_multiplier", 1.0)))
        return jsonify({"id": ni_id})

    @app.route(f"/{panel_path}/api/nodes/<int:node_id>/inbounds/<int:ni_id>", methods=["PUT"])
    def api_node_inbound_update(node_id, ni_id):
        data = request.json
        db.update_node_inbound(ni_id, **data)
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/nodes/<int:node_id>/inbounds/<int:ni_id>", methods=["DELETE"])
    def api_node_inbound_delete(node_id, ni_id):
        db.delete_node_inbound(ni_id)
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/nodes/test", methods=["POST"])
    def api_nodes_test():
        data = request.json or {}
        for k in ("address", "username", "password"):
            if not data.get(k):
                return jsonify({"ok": False, "error": f"missing {k}"}), 400
        inbound_id = int(data.get("inbound_id") or 1)
        try:
            xui = XUIClient(data["address"], data["username"], data["password"], data.get("proxy_url"))
            ok = xui.test_connection()
            inbound = xui.get_inbound(inbound_id) if ok else None
            return jsonify({"ok": ok, "protocol": inbound.get("protocol") if inbound else None})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route(f"/{panel_path}/api/nodes/<int:node_id>/test")
    def api_node_test(node_id):
        node = db.get_node(node_id)
        if not node:
            return jsonify({"ok": False, "error": "not found"}), 404
        try:
            xui = XUIClient(node["address"], node["username"], node["password"], node.get("proxy_url"))
            ok = xui.test_connection()
            return jsonify({"ok": ok})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route(f"/{panel_path}/api/nodes/<int:node_id>/inbounds/<int:ni_id>/test")
    def api_node_inbound_test(node_id, ni_id):
        ni = db.get_node_inbound_with_node(ni_id)
        if not ni:
            return jsonify({"ok": False, "error": "not found"}), 404
        try:
            xui = XUIClient(ni["address"], ni["username"], ni["password"], ni.get("proxy_url"))
            ok = xui.test_connection()
            inbound = xui.get_inbound(ni["inbound_id"]) if ok else None
            return jsonify({"ok": ok, "protocol": inbound.get("protocol") if inbound else None})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route(f"/{panel_path}/api/update")
    def api_update_check():
        return jsonify(updater.check_update())

    @app.route(f"/{panel_path}/api/update", methods=["POST"])
    def api_update_apply():
        def _do():
            try:
                ok = updater.apply_update()
                if ok:
                    try:
                        subprocess.Popen(["systemctl", "restart", "ghostgate"])
                    except Exception:
                        time.sleep(1)
                        os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/settings")
    def api_settings_get():
        env_path = os.getenv("ENV_PATH", os.path.join(base_dir, ".env"))
        return jsonify(dict(dotenv_values(env_path)))

    @app.route(f"/{panel_path}/api/settings", methods=["POST"])
    def api_settings_save():
        env_path = os.getenv("ENV_PATH", os.path.join(base_dir, ".env"))
        for key, val in request.json.items():
            set_key(env_path, key, str(val))
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/restart", methods=["POST"])
    def api_restart():
        try:
            subprocess.Popen(["systemctl", "restart", "ghostgate"])
        except Exception:
            def _reexec():
                time.sleep(1)
                os.execv(sys.executable, [sys.executable] + sys.argv)
            threading.Thread(target=_reexec, daemon=True).start()
        return jsonify({"ok": True})

    @app.route(f"/{panel_path}/api/logs")
    def api_logs():
        log_file = os.getenv("LOG_FILE", "/var/log/ghostgate.log")
        try:
            with open(log_file) as f:
                lines = f.readlines()[-200:]
            return "".join(lines), 200, {"Content-Type": "text/plain"}
        except Exception:
            return "", 200, {"Content-Type": "text/plain"}

    @app.route(f"/{panel_path}/api/logs/stream")
    def api_logs_stream():
        log_file = os.getenv("LOG_FILE", "/var/log/ghostgate.log")
        def _gen():
            try:
                with open(log_file) as f:
                    f.seek(0, 2)
                    last_send = time.time()
                    while True:
                        line = f.readline()
                        if line:
                            yield f"data: {line.rstrip()}\n\n"
                            last_send = time.time()
                        else:
                            if time.time()-last_send >= 10:
                                yield ": heartbeat\n\n"
                                last_send = time.time()
                            time.sleep(0.5)
            except Exception:
                pass
        return Response(_gen(), content_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    def _err(code):
        if request.path.startswith(f"/{panel_path}"):
            return _err_pages.get(code, ""), code
        return "", code

    @app.errorhandler(400)
    def err400(e):
        return _err(400)

    @app.errorhandler(403)
    def err403(e):
        return _err(403)

    @app.errorhandler(404)
    def err404(e):
        return _err(404)

    @app.errorhandler(405)
    def err405(e):
        return _err(405)

    @app.errorhandler(500)
    def err500(e):
        return _err(500)
