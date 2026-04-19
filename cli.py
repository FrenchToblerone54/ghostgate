import os
import sys
import uuid
import shlex
import subprocess
from dotenv import load_dotenv
import psutil
from datetime import datetime, timezone, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich.progress import BarColumn, Progress, TextColumn
from rich import box
import database as db
import updater

console = Console()
ACC = "#00e5a0"
DANGER = "#ef4444"
WARN = "#f59e0b"
BLUE = "#3b82f6"
MUTED = "#8ba3bc"
DIM = "#4a6380"

def _fmt_bytes(b):
    if b < 1024: return f"{b} B"
    if b < 1048576: return f"{b/1024:.1f} KB"
    if b < 1073741824: return f"{b/1048576:.2f} MB"
    return f"{b/1073741824:.2f} GB"

def _fmt_gb(b): return f"{b/1073741824:.2f} GB"

def _status_text(sub):
    now = datetime.now(timezone.utc)
    limit = int(sub["data_gb"]*1073741824) if sub["data_gb"] > 0 else 0
    used = sub.get("used_bytes") or 0
    exp = sub.get("expire_at")
    is_exp = bool(exp) and datetime.fromisoformat(exp).replace(tzinfo=timezone.utc) < now
    is_over = limit > 0 and used >= limit
    is_dis = sub.get("enabled") == 0
    if is_dis: return Text("● Disabled", style=MUTED)
    if is_exp: return Text("● Expired", style=DANGER)
    if is_over: return Text("● Over Limit", style=DANGER)
    return Text("● Active", style=ACC)

def _data_bar(sub):
    used = sub.get("used_bytes") or 0
    limit = int(sub["data_gb"]*1073741824) if sub["data_gb"] > 0 else 0
    if limit == 0:
        return Text(f"{_fmt_gb(used)} / ∞", style=MUTED)
    pct = min(1.0, used/limit)
    filled = int(pct*10)
    bar = "█"*filled + "░"*(10-filled)
    color = DANGER if pct > 0.85 else WARN if pct > 0.65 else ACC
    return Text(f"{bar} {_fmt_gb(used)}/{sub['data_gb']} GB", style=color)

def _exp_str(sub):
    if not sub.get("expire_at"): return Text("Never", style=MUTED)
    try:
        exp = datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc)
        diff = exp - datetime.now(timezone.utc)
        date_str = exp.strftime("%Y-%m-%d")
        if diff.total_seconds() < 0: return Text(f"{date_str} (expired)", style=DANGER)
        days = diff.days
        color = DANGER if days < 3 else WARN if days < 7 else MUTED
        return Text(f"{date_str} ({days}d)", style=color)
    except Exception:
        return Text(sub["expire_at"][:10], style=MUTED)

def _tmult(ni):
    v = ni.get("traffic_multiplier")
    return 1.0 if v is None else float(v)

def _parse_opts(raw_args):
    opts = {}
    i = 0
    while i < len(raw_args):
        if raw_args[i].startswith("--"):
            key = raw_args[i][2:]
            val = raw_args[i+1] if i+1 < len(raw_args) and not raw_args[i+1].startswith("--") else "true"
            opts[key] = val
            i += 2 if val != "true" else 1
        else:
            opts.setdefault("_pos", []).append(raw_args[i])
            i += 1
    return opts

def cmd_list(args):
    opts = _parse_opts(args)
    search = opts.get("search") or opts.get("s")
    subs, total = db.get_subs(page=1, per_page=0, search=search)
    for sub in subs:
        sub["node_names"] = [sn["name"] for sn in db.get_sub_nodes(sub["id"])]
    now = datetime.now(timezone.utc)
    active = sum(1 for s in subs if s.get("enabled") != 0
        and not (s.get("expire_at") and datetime.fromisoformat(s["expire_at"]).replace(tzinfo=timezone.utc) < now)
        and not (s.get("data_gb", 0) > 0 and (s.get("used_bytes") or 0) >= int(s["data_gb"]*1073741824)))
    tbl = Table(box=box.ROUNDED, border_style=DIM, header_style=f"bold {MUTED}", show_lines=False)
    tbl.add_column("ID", style=f"bold {ACC}", no_wrap=True)
    tbl.add_column("Comment", style="bold white")
    tbl.add_column("Data", no_wrap=True)
    tbl.add_column("Expires", no_wrap=True)
    tbl.add_column("Nodes", style=MUTED)
    tbl.add_column("Status", no_wrap=True)
    for sub in subs:
        nodes_str = ", ".join(sub["node_names"]) if sub["node_names"] else "—"
        tbl.add_row(
            sub["id"][:16]+"…",
            sub.get("comment") or "—",
            _data_bar(sub),
            _exp_str(sub),
            nodes_str,
            _status_text(sub),
        )
    title = f"[bold white]Subscriptions[/]  [{MUTED}]{total} total, {active} active[/]"
    if search:
        title += f"  [{WARN}]search: {search}[/]"
    console.print(Panel(tbl, title=title, border_style=DIM, padding=(0, 1)))

def cmd_stats(args):
    if not args:
        console.print(f"[{DANGER}]Usage: ghostgate stats <id or comment>[/]")
        return
    key = args[0]
    sub = db.get_sub(key) or db.get_sub_by_comment(key)
    if not sub:
        console.print(f"[{DANGER}]Not found: {key}[/]")
        return
    stats = db.get_stats(sub["id"])
    snodes = db.get_sub_nodes(sub["id"])
    used = sub.get("used_bytes") or 0
    limit = int(sub["data_gb"]*1073741824) if sub["data_gb"] > 0 else 0
    pct = min(100, int(used*100/limit)) if limit > 0 else 0
    filled = int(pct/10)
    bar = "█"*filled + "░"*(10-filled)
    bar_color = DANGER if pct > 85 else WARN if pct > 65 else ACC
    data_line = f"[{bar_color}]{bar}[/] {_fmt_gb(used)} / {sub['data_gb']} GB  [{MUTED}]({pct}%)[/]" if limit > 0 else f"[{MUTED}]────────── ∞  {_fmt_gb(used)} used[/]"
    exp = sub.get("expire_at")
    if exp:
        try:
            dt = datetime.fromisoformat(exp).replace(tzinfo=timezone.utc)
            diff = dt - datetime.now(timezone.utc)
            exp_str = dt.strftime("%Y-%m-%d %H:%M") + (f"  [{MUTED}]({diff.days}d left)[/]" if diff.total_seconds() > 0 else f"  [{DANGER}](expired)[/]")
        except Exception:
            exp_str = exp[:16]
    else:
        exp_str = f"[{MUTED}]Never[/]"
    nodes_str = ", ".join(sn["name"] for sn in snodes) if snodes else f"[{MUTED}]None[/]"
    ip_str = str(sub.get("ip_limit") or 0) if sub.get("ip_limit") else f"[{MUTED}]Unlimited[/]"
    lines = [
        f"  [{MUTED}]ID[/]          [{ACC}]{sub['id']}[/]",
        f"  [{MUTED}]Data[/]        {data_line}",
        f"  [{MUTED}]Expires[/]     {exp_str}",
        f"  [{MUTED}]IP Limit[/]    {ip_str}",
        f"  [{MUTED}]Nodes[/]       {nodes_str}",
        f"  [{MUTED}]Status[/]      {_status_text(sub).markup if hasattr(_status_text(sub),'markup') else _status_text(sub)}",
        f"  [{MUTED}]Created[/]     [{MUTED}]{(sub.get('created_at') or '')[:10]}[/]",
        f"  [{MUTED}]Accesses[/]    [{MUTED}]{stats.get('access_count', 0)}[/]",
    ]
    if stats.get("last_access"):
        lines.append(f"  [{MUTED}]Last Access[/] [{MUTED}]{stats['last_access'][:16]}[/]")
    if stats.get("last_ua"):
        lines.append(f"  [{MUTED}]Last UA[/]     [{DIM}]{stats['last_ua'][:60]}[/]")
    if (sub.get("show_multiplier") or 1) > 1:
        lines.append(f"  [{MUTED}]Show ×[/]      [{WARN}]×{sub['show_multiplier']}[/]")
    title = f"[bold white]{sub.get('comment') or sub['id']}[/]  {_status_text(sub)}"
    console.print(Panel("\n".join(lines), title=title, border_style=DIM, padding=(0, 1)))

def cmd_nodes(args):
    nodes = db.get_nodes()
    if not nodes:
        console.print(f"[{MUTED}]No nodes configured.[/]")
        return
    lines = []
    for n in nodes:
        status_text = f"[{ACC}]● On[/]" if n.get("enabled") else f"[{DANGER}]● Off[/]"
        proxy_text = f"  [{MUTED}]Proxy: {n['proxy_url']}[/]" if n.get("proxy_url") else ""
        lines.append(f"[bold white][{n['id']}] {n['name']}[/]  [{BLUE}]{n['address']}[/]  {status_text}{proxy_text}")
        for ni in db.get_node_inbounds(n["id"]):
            ni_status = f"[{ACC}]On[/]" if ni.get("enabled") else f"[{DANGER}]Off[/]"
            mult = _tmult(ni)
            mult_str = f"  [{WARN}]×{mult:g}[/]" if mult != 1.0 else ""
            lines.append(f"  [{DIM}]└─[/] [{MUTED}][{ni['id']}][/] {ni['name'] or 'Inbound '+str(ni['inbound_id'])}  [{MUTED}]ID:{ni['inbound_id']}[/]{mult_str}  {ni_status}")
    console.print(Panel("\n".join(lines), title=f"[bold white]Nodes[/]", border_style=DIM, padding=(0, 1)))

def cmd_subnodes(args):
    if args:
        try:
            node_id = int(args[0])
        except ValueError:
            console.print(f"[{DANGER}]Usage: ghostgate subnodes [node_id][/]")
            return
        node = db.get_node(node_id)
        if not node:
            console.print(f"[{DANGER}]Node not found: {node_id}[/]")
            return
        inbounds = db.get_node_inbounds(node_id)
        if not inbounds:
            console.print(f"[{MUTED}]No sub-nodes for node [{node_id}] {node['name']}[/]")
            return
        lines = [f"[bold white]Sub-nodes for [{node_id}] {node['name']}[/]"]
        for ni in inbounds:
            ni_status = f"[{ACC}]On[/]" if ni.get("enabled") else f"[{DANGER}]Off[/]"
            mult = _tmult(ni)
            mult_str = f"  [{WARN}]×{mult:g}[/]" if mult != 1.0 else ""
            lines.append(f"  [{MUTED}][{ni['id']}][/] {ni['name'] or 'Inbound '+str(ni['inbound_id'])}  [{MUTED}]ID:{ni['inbound_id']}[/]{mult_str}  {ni_status}")
        console.print(Panel("\n".join(lines), border_style=DIM, padding=(0, 1)))
        return
    nodes = db.get_nodes()
    if not nodes:
        console.print(f"[{MUTED}]No nodes configured.[/]")
        return
    lines = []
    has_any = False
    for n in nodes:
        inbounds = db.get_node_inbounds(n["id"])
        if not inbounds:
            continue
        has_any = True
        lines.append(f"[bold white][{n['id']}] {n['name']}[/]")
        for ni in inbounds:
            ni_status = f"[{ACC}]On[/]" if ni.get("enabled") else f"[{DANGER}]Off[/]"
            mult = _tmult(ni)
            mult_str = f"  [{WARN}]×{mult:g}[/]" if mult != 1.0 else ""
            lines.append(f"  [{DIM}]└─[/] [{MUTED}][{ni['id']}][/] {ni['name'] or 'Inbound '+str(ni['inbound_id'])}  [{MUTED}]ID:{ni['inbound_id']}[/]{mult_str}  {ni_status}")
    if not has_any:
        console.print(f"[{MUTED}]No sub-nodes configured.[/]")
        return
    console.print(Panel("\n".join(lines), title=f"[bold white]Sub-nodes[/]", border_style=DIM, padding=(0, 1)))

def cmd_editnode(args):
    if not args:
        console.print(f"[{DANGER}]Usage: ghostgate editnode <node_id> [--name X] [--addr X] [--user X] [--pass X] [--proxy X] [--enable] [--disable][/]")
        return
    try:
        node_id = int(args[0])
    except ValueError:
        console.print(f"[{DANGER}]Node ID must be a number.[/]")
        return
    node = db.get_node(node_id)
    if not node:
        console.print(f"[{DANGER}]Node not found: {node_id}[/]")
        return
    opts = _parse_opts(args[1:])
    updates = {}
    if "name" in opts: updates["name"] = opts["name"]
    if "addr" in opts: updates["address"] = opts["addr"]
    if "user" in opts: updates["username"] = opts["user"]
    if "pass" in opts: updates["password"] = opts["pass"]
    if "proxy" in opts: updates["proxy_url"] = opts["proxy"] or None
    if "enable" in opts: updates["enabled"] = 1
    if "disable" in opts: updates["enabled"] = 0
    if not updates:
        console.print(f"[{WARN}]No valid changes provided.[/]")
        return
    db.update_node(node_id, **updates)
    if "enabled" in updates:
        from panel import _disable_node_clients, _enable_node_clients
        if updates["enabled"]:
            _enable_node_clients(node_id)
        else:
            _disable_node_clients(node_id)
    updated = db.get_node(node_id)
    st = f"[{ACC}]On[/]" if updated.get("enabled") else f"[{DANGER}]Off[/]"
    console.print(f"[{ACC}]Updated node:[/] [{MUTED}][{node_id}][/] {updated['name']}  {st}")

def cmd_addsubnode(args):
    opts = _parse_opts(args)
    if "node" not in opts or "inbound" not in opts:
        console.print(f"[{DANGER}]Usage: ghostgate addsubnode --node <node_id> --inbound <id> [--name X] [--multiplier N][/]")
        return
    try:
        node_id = int(opts.get("node", 0))
        inbound_id = int(opts.get("inbound", 0))
        multiplier = max(0.0, float(opts.get("multiplier", 1.0)))
    except ValueError:
        console.print(f"[{DANGER}]Node ID, inbound ID, and multiplier must be numeric.[/]")
        return
    if node_id <= 0 or inbound_id <= 0:
        console.print(f"[{DANGER}]Node ID and inbound ID must be greater than 0.[/]")
        return
    node = db.get_node(node_id)
    if not node:
        console.print(f"[{DANGER}]Node not found: {node_id}[/]")
        return
    from xui_client import XUIClient
    try:
        xui = XUIClient(node["address"], node["username"], node["password"], node.get("proxy_url"))
        inbound = xui.get_inbound(inbound_id)
        proto = (inbound.get("protocol") or "").lower() if inbound else ""
        if proto not in ("vless", "vmess"):
            console.print(f"[{DANGER}]Unsupported protocol '{proto}': only vless and vmess are supported.[/]")
            return
    except Exception as e:
        console.print(f"[{DANGER}]Failed to verify inbound: {e}[/]")
        return
    ni_id = db.add_node_inbound(node_id, inbound_id, opts.get("name"), multiplier)
    label = opts.get("name") or f"Inbound {inbound_id}"
    mult_str = f" [{WARN}]×{multiplier:g}[/]" if multiplier != 1.0 else ""
    console.print(f"[{ACC}]Sub-node added:[/] [{MUTED}][{ni_id}][/] {label}{mult_str} [{MUTED}]on node [{node_id}] {node['name']}[/]")

def cmd_editsubnode(args):
    if not args:
        console.print(f"[{DANGER}]Usage: ghostgate editsubnode <subnode_id> [--name X] [--inbound N] [--multiplier N] [--enable] [--disable][/]")
        return
    try:
        ni_id = int(args[0])
    except ValueError:
        console.print(f"[{DANGER}]Sub-node ID must be a number.[/]")
        return
    ni = db.get_node_inbound(ni_id)
    if not ni:
        console.print(f"[{DANGER}]Sub-node not found: {ni_id}[/]")
        return
    opts = _parse_opts(args[1:])
    if "move-up" in opts or "move-down" in opts:
        inbounds = db.get_node_inbounds(ni["node_id"])
        ids = [n["id"] for n in inbounds]
        if ni_id in ids:
            idx = ids.index(ni_id)
            if "move-up" in opts and idx > 0:
                ids[idx], ids[idx-1] = ids[idx-1], ids[idx]
                db.reorder_node_inbounds(ni["node_id"], ids)
                console.print(f"[{ACC}]Moved sub-node [{ni_id}] up.[/]")
            elif "move-down" in opts and idx < len(ids)-1:
                ids[idx], ids[idx+1] = ids[idx+1], ids[idx]
                db.reorder_node_inbounds(ni["node_id"], ids)
                console.print(f"[{ACC}]Moved sub-node [{ni_id}] down.[/]")
            else:
                console.print(f"[{WARN}]Already at boundary.[/]")
        return
    updates = {}
    if "name" in opts:
        updates["name"] = opts["name"]
    if "inbound" in opts:
        try:
            updates["inbound_id"] = int(opts["inbound"])
        except ValueError:
            console.print(f"[{DANGER}]Inbound ID must be a number.[/]")
            return
    if "multiplier" in opts:
        try:
            updates["traffic_multiplier"] = max(0.0, float(opts["multiplier"]))
        except ValueError:
            console.print(f"[{DANGER}]Multiplier must be a number.[/]")
            return
    if "enable" in opts:
        updates["enabled"] = 1
    if "disable" in opts:
        updates["enabled"] = 0
    if not updates:
        console.print(f"[{WARN}]No valid changes provided.[/]")
        return
    db.update_node_inbound(ni_id, **updates)
    if "traffic_multiplier" in updates and abs(updates["traffic_multiplier"]-_tmult(ni))>0.001:
        from panel import _checkpoint_subnode_traffic, _refresh_subnode_client_limits
        _checkpoint_subnode_traffic(ni_id, _tmult(ni))
        _refresh_subnode_client_limits(ni_id)
    if "enabled" in updates:
        from panel import _disable_subnode_clients, _enable_subnode_clients
        if updates["enabled"]:
            _enable_subnode_clients(ni_id)
        else:
            _disable_subnode_clients(ni_id)
    updated = db.get_node_inbound(ni_id) or ni
    st = f"[{ACC}]On[/]" if updated.get("enabled") else f"[{DANGER}]Off[/]"
    mult = _tmult(updated)
    mult_str = f" [{WARN}]×{mult:g}[/]" if mult != 1.0 else ""
    console.print(f"[{ACC}]Updated sub-node:[/] [{MUTED}][{ni_id}][/] {updated.get('name') or 'Inbound '+str(updated.get('inbound_id'))}{mult_str} [{MUTED}]ID:{updated.get('inbound_id')}[/] {st}")

def cmd_delsubnode(args):
    if not args:
        console.print(f"[{DANGER}]Usage: ghostgate delsubnode <subnode_id>[/]")
        return
    try:
        ni_id = int(args[0])
    except ValueError:
        console.print(f"[{DANGER}]Sub-node ID must be a number.[/]")
        return
    ni = db.get_node_inbound_with_node(ni_id)
    if not ni:
        console.print(f"[{DANGER}]Sub-node not found: {ni_id}[/]")
        return
    db.delete_node_inbound(ni_id)
    console.print(f"[{ACC}]Deleted sub-node:[/] [{MUTED}][{ni_id}][/] {ni.get('inbound_name') or ni['name']} [{MUTED}](inbound {ni['inbound_id']})[/]")

def cmd_status(args):
    subs, total = db.get_subs(page=1, per_page=0)
    now = datetime.now(timezone.utc)
    active = sum(1 for s in subs if s.get("enabled") != 0
        and not (s.get("expire_at") and datetime.fromisoformat(s["expire_at"]).replace(tzinfo=timezone.utc) < now)
        and not (s.get("data_gb", 0) > 0 and (s.get("used_bytes") or 0) >= int(s["data_gb"]*1073741824)))
    inbounds = db.get_all_node_inbounds()
    cpu = psutil.cpu_percent(interval=0.3)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load = psutil.getloadavg()
    def _bar(pct):
        filled = int(pct/10)
        color = DANGER if pct > 85 else WARN if pct > 65 else ACC
        return f"[{color}]{'█'*filled}{'░'*(10-filled)}[/] [{MUTED}]{pct:.1f}%[/]"
    lines = [
        f"  [{MUTED}]Version[/]   [{ACC}]v{updater.VERSION}[/]",
        f"  [{MUTED}]CPU[/]       {_bar(cpu)}  [{MUTED}]{psutil.cpu_count()} cores[/]",
        f"  [{MUTED}]RAM[/]       {_bar(ram.percent)}  [{MUTED}]{ram.used//1048576} MB / {ram.total//1048576} MB[/]",
        f"  [{MUTED}]Disk[/]      {_bar(disk.percent)}  [{MUTED}]{disk.used/1073741824:.1f} GB / {disk.total/1073741824:.1f} GB[/]",
        f"  [{MUTED}]Load[/]      [{MUTED}]{load[0]:.2f}  {load[1]:.2f}  {load[2]:.2f}[/]",
        f"  [{MUTED}]Subs[/]      [{ACC}]{active}[/] [{MUTED}]active / {total} total[/]",
        f"  [{MUTED}]Sub-nodes[/] [{MUTED}]{len(inbounds)}[/]",
    ]
    console.print(Panel("\n".join(lines), title=f"[bold white]GhostGate[/]", border_style=DIM, padding=(0, 1)))

def cmd_create(args):
    from xui_client import XUIClient
    opts = _parse_opts(args)
    comment = opts.get("comment", "")
    note = opts.get("note") or None
    data_gb = float(opts.get("data", opts.get("data-gb", 0)))
    days = int(opts.get("days", 0))
    firstuse_days = int(opts.get("firstuse-days", 0))
    firstuse_seconds = int(opts.get("firstuse-seconds", opts.get("firstuse", 0)))
    expire_after_first_use_seconds = max(0, firstuse_seconds or (firstuse_days * 86400))
    ip_limit = int(opts.get("ip", 0))
    show_multiplier = max(1, int(opts.get("show-multiplier", 1)))
    node_ids_raw = opts.get("nodes", "")
    all_inbounds = db.get_all_node_inbounds()
    if node_ids_raw == "all":
        node_ids = [ni["id"] for ni in all_inbounds]
    elif node_ids_raw == "none" or not node_ids_raw:
        node_ids = []
    else:
        node_ids = [int(x) for x in node_ids_raw.split(",")]
    custom_id = opts.get("id") or None
    if custom_id and db.get_sub(custom_id):
        console.print(f"[{DANGER}]ID already exists: {custom_id}[/]")
        return
    sub_id = db.create_sub(comment=comment, note=note, data_gb=data_gb, days=days, ip_limit=ip_limit, show_multiplier=show_multiplier, sub_id=custom_id, expire_after_first_use_seconds=expire_after_first_use_seconds)
    sub = db.get_sub(sub_id)
    client_uuid = str(uuid.uuid4())
    expire_ms = 0
    if sub.get("expire_at"):
        try: expire_ms = int(datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp()*1000)
        except Exception: pass
    expiry_time = -expire_after_first_use_seconds*1000 if expire_after_first_use_seconds>0 and not sub.get("expire_at") else expire_ms
    errors = []
    for node_id in node_ids:
        ni = db.get_node_inbound_with_node(node_id)
        if not ni: continue
        try:
            xui = XUIClient(ni["address"], ni["username"], ni["password"], ni.get("proxy_url"))
            mult = _tmult(ni)
            total_limit_bytes = int(data_gb * 1073741824 / mult) if data_gb > 0 and mult != 0 else 0
            email = f"{sub_id}-{node_id}"
            client = xui.make_client(email, client_uuid, expiry_time, ip_limit, sub_id, comment, total_limit_bytes)
            ok = xui.add_client(ni["inbound_id"], client)
            if ok: db.add_sub_node(sub_id, node_id, client_uuid, email)
            else: errors.append(f"inbound {node_id}: failed")
        except Exception as e:
            errors.append(f"inbound {node_id}: {e}")
    base_url = os.getenv("BASE_URL", "").rstrip("/")
    sub_url = f"{base_url}/sub/{sub_id}" if base_url else f"/sub/{sub_id}"
    lines = [
        f"  [{MUTED}]ID[/]    [{ACC}]{sub_id}[/]",
        f"  [{MUTED}]UUID[/]  [{DIM}]{client_uuid}[/]",
        f"  [{MUTED}]URL[/]   [{BLUE}]{sub_url}[/]",
    ]
    if errors:
        lines.append(f"  [{WARN}]Errors: {'; '.join(errors)}[/]")
    console.print(Panel("\n".join(lines), title=f"[bold {ACC}]Created: {comment or sub_id}[/]", border_style=ACC, padding=(0, 1)))

def cmd_delete(args):
    from xui_client import XUIClient
    if not args:
        console.print(f"[{DANGER}]Usage: ghostgate delete <id or comment>[/]")
        return
    key = " ".join(args)
    sub = db.get_sub(key) or db.get_sub_by_comment(key)
    if not sub:
        console.print(f"[{DANGER}]Not found: {key}[/]")
        return
    label = sub.get("comment") or sub["id"]
    console.print(f"[{WARN}]Delete [bold]{label}[/bold]? (y/N)[/] ", end="")
    if input().strip().lower() != "y":
        console.print(f"[{MUTED}]Aborted.[/]")
        return
    snodes = db.get_sub_nodes(sub["id"])
    for sn in snodes:
        try:
            xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
            xui.delete_client(sn["inbound_id"], sn["client_uuid"])
        except Exception: pass
    db.delete_sub(sub["id"])
    console.print(f"[{ACC}]Deleted: {label}[/]")

def cmd_edit(args):
    from xui_client import XUIClient
    pos = [a for a in args if not a.startswith("--")]
    if not pos:
        console.print(f"[{DANGER}]Usage: ghostgate edit <id or comment> [--data GB] [--days N] [--firstuse-days N] [--firstuse-seconds N] [--no-firstuse] [--comment X] [--note X] [--ip N][/]")
        return
    key = pos[0]
    sub = db.get_sub(key) or db.get_sub_by_comment(key)
    if not sub:
        console.print(f"[{DANGER}]Not found: {key}[/]")
        return
    opts = _parse_opts(args[1:])
    updates = {}
    if "comment" in opts: updates["comment"] = opts["comment"]
    if "note" in opts: updates["note"] = opts["note"] or None
    if "data" in opts: updates["data_gb"] = float(opts["data"])
    if "days" in opts: updates["days"] = int(opts["days"])
    if "firstuse-days" in opts or "firstuse-seconds" in opts or "firstuse" in opts:
        firstuse_days = int(opts.get("firstuse-days", 0))
        firstuse_seconds = int(opts.get("firstuse-seconds", opts.get("firstuse", 0)))
        updates["expire_after_first_use_seconds"] = max(0, firstuse_seconds or (firstuse_days * 86400))
        updates["expire_at"] = None
    if "no-firstuse" in opts: updates["expire_after_first_use_seconds"] = 0
    if "ip" in opts: updates["ip_limit"] = int(opts["ip"])
    if "enable" in opts: updates["enabled"] = 1
    if "disable" in opts: updates["enabled"] = 0
    if "show-multiplier" in opts: updates["show_multiplier"] = max(1, int(opts["show-multiplier"]))
    if "remove-data" in opts: updates["data_gb"] = max(0, (sub.get("data_gb") or 0) - float(opts["remove-data"]))
    if "no-expire" in opts: updates["expire_at"] = None
    elif "remove-days" in opts and sub.get("expire_at"):
        try: updates["expire_at"] = (datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc) - timedelta(days=int(opts["remove-days"]))).isoformat()
        except Exception: pass
    if not updates:
        console.print(f"[{WARN}]Nothing to update. Use --data, --days, --remove-data, --remove-days, --no-expire, --comment, --note, --ip, --enable, --disable[/]")
        return
    db.update_sub(sub["id"], **updates)
    if "enabled" in updates:
        if updates["enabled"]:
            db.reset_sub_node_disabled(sub["id"])
        snodes = db.get_sub_nodes(sub["id"])
        for sn in snodes:
            try:
                xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
                xui.set_client_enabled(sn["inbound_id"], sn["client_uuid"], sn["email"], bool(updates["enabled"]))
            except Exception: pass
    console.print(f"[{ACC}]Updated: {sub.get('comment') or sub['id']}[/]")
    cmd_stats([sub["id"]])

def cmd_addnode(args):
    from xui_client import XUIClient
    opts = _parse_opts(args)
    name = opts.get("name")
    addr = opts.get("addr")
    user = opts.get("user")
    pwd = opts.get("pass")
    inbound = int(opts.get("inbound", 1))
    proxy = opts.get("proxy")
    multiplier = max(0.0, float(opts.get("multiplier", 1.0)))
    if not all([name, addr, user, pwd]):
        console.print(f"[{DANGER}]Usage: ghostgate addnode --name X --addr http://host:port --user X --pass X --inbound N [--proxy http://...] [--multiplier N][/]")
        return
    node_id = db.add_node(name, addr, user, pwd, proxy)
    ni_id = db.add_node_inbound(node_id, inbound, name, multiplier)
    mult_str = f" [{WARN}]×{multiplier:g}[/]" if multiplier != 1.0 else ""
    console.print(f"[{ACC}]Node added:[/] [{MUTED}][{node_id}][/] {name}{mult_str}  [{BLUE}]{addr}[/]  [{MUTED}]sub-node [{ni_id}] inbound {inbound}[/]")

def cmd_delnode(args):
    if not args:
        console.print(f"[{DANGER}]Usage: ghostgate delnode <node_id>[/]")
        return
    try:
        node_id = int(args[0])
    except ValueError:
        console.print(f"[{DANGER}]Node ID must be a number.[/]")
        return
    node = db.get_node(node_id)
    if not node:
        console.print(f"[{DANGER}]Node not found: {node_id}[/]")
        return
    console.print(f"[{WARN}]Delete node [bold][{node_id}] {node['name']}[/bold]? (y/N)[/] ", end="")
    if input().strip().lower() != "y":
        console.print(f"[{MUTED}]Aborted.[/]")
        return
    db.delete_node(node_id)
    console.print(f"[{ACC}]Deleted node:[/] [{MUTED}][{node_id}][/] {node['name']}")

def cmd_bot(args):
    opts = _parse_opts(args)
    env_path = os.getenv("ENV_PATH") or ("/opt/ghostgate/.env" if os.path.exists("/opt/ghostgate/.env") else ".env")
    if "enable" in opts:
        from dotenv import set_key
        set_key(env_path, "BOT_ENABLED", "true")
        console.print(f"[{ACC}]Bot enabled.[/] [{MUTED}]Restart service to apply: systemctl restart ghostgate[/]")
    elif "disable" in opts:
        from dotenv import set_key
        set_key(env_path, "BOT_ENABLED", "false")
        console.print(f"[{ACC}]Bot disabled.[/] [{MUTED}]Restart service to apply: systemctl restart ghostgate[/]")
    else:
        enabled = os.getenv("BOT_ENABLED", "true").lower() != "false"
        st = f"[{ACC}]enabled[/]" if enabled else f"[{DANGER}]disabled[/]"
        console.print(f"[bold white]Telegram Bot:[/] {st}  [{MUTED}]Use --enable or --disable[/]")

def cmd_regen(args):
    from xui_client import XUIClient
    from nanoid import generate
    if not args:
        console.print(f"[{DANGER}]Usage: ghostgate regen <id or comment>[/]")
        return
    key = args[0]
    sub = db.get_sub(key) or db.get_sub_by_comment(key)
    if not sub:
        console.print(f"[{DANGER}]Not found: {key}[/]")
        return
    new_id = generate(size=20)
    snodes = db.get_sub_nodes(sub["id"])
    for sn in snodes:
        try:
            xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
            xui.update_client_email_subid(sn["inbound_id"], sn["client_uuid"], sn["email"], f"{new_id}-{sn['node_id']}", new_id)
        except Exception: pass
    db.rename_sub(sub["id"], new_id)
    base_url = os.getenv("BASE_URL", "").rstrip("/")
    sub_url = f"{base_url}/sub/{new_id}" if base_url else f"/sub/{new_id}"
    console.print(Panel(f"  [{MUTED}]New ID[/]  [{ACC}]{new_id}[/]\n  [{MUTED}]URL[/]     [{BLUE}]{sub_url}[/]", title=f"[bold {ACC}]Regenerated: {sub.get('comment') or sub['id']}[/]", border_style=ACC, padding=(0, 1)))

def cmd_regen_uuid(args):
    from xui_client import XUIClient
    if not args:
        console.print(f"[{DANGER}]Usage: ghostgate regen-uuid <id or comment>[/]")
        return
    sub = db.get_sub(args[0]) or db.get_sub_by_comment(args[0])
    if not sub:
        console.print(f"[{DANGER}]Not found: {args[0]}[/]")
        return
    new_uuid = str(uuid.uuid4())
    errors = []
    for sn in db.get_sub_nodes(sub["id"]):
        try:
            xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
            ok = xui.rotate_client_uuid(sn["inbound_id"], sn["client_uuid"], sn["email"], new_uuid)
            if ok:
                db.update_sub_node_uuid(sub["id"], sn["node_id"], new_uuid)
            else:
                errors.append(f"node {sn['node_id']}: failed")
        except Exception as e:
            errors.append(f"node {sn['node_id']}: {e}")
    if errors:
        console.print(f"[{WARN}]Errors: {', '.join(errors)}[/]")
    console.print(f"[{ACC}]UUID regenerated:[/] [{MUTED}]{new_uuid}[/]  [{MUTED}]Sub: {sub.get('comment') or sub['id']}[/]")

def cmd_reset_traffic(args):
    from xui_client import XUIClient
    if not args:
        console.print(f"[{DANGER}]Usage: ghostgate reset-traffic <id or comment>[/]")
        return
    sub = db.get_sub(args[0]) or db.get_sub_by_comment(args[0])
    if not sub:
        console.print(f"[{DANGER}]Not found: {args[0]}[/]")
        return
    for sn in db.get_sub_nodes(sub["id"]):
        try:
            xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
            xui.reset_client_traffic(sn["inbound_id"], sn["email"])
        except Exception:
            pass
    db.reset_sub_traffic(sub["id"])
    console.print(f"[{ACC}]Traffic reset:[/] [{MUTED}]{sub.get('comment') or sub['id']}[/]")

def cmd_update(args):
    console.print(f"[{MUTED}]Current version:[/] [{ACC}]v{updater.VERSION}[/]")
    console.print(f"[{MUTED}]Checking for updates...[/]")
    info = updater.check_update()
    if not info.get("update_available"):
        console.print(f"[{ACC}]Already up to date.[/]")
        return
    console.print(f"[{WARN}]Update found:[/] [{ACC}]v{info['latest']}[/]")
    console.print(f"[{MUTED}]Downloading and applying update...[/]")
    if updater.apply_update():
        try:
            active = subprocess.run(["systemctl", "is-active", "ghostgate"], capture_output=True, text=True).stdout.strip() == "active"
        except Exception:
            active = False
        if active:
            console.print(f"[{ACC}]Updated. Restarting service...[/]")
            subprocess.run(["systemctl", "restart", "ghostgate"], check=False)
        else:
            updater.restart_self()
        return
    console.print(f"[{DANGER}]Update failed — check logs.[/]")

def cmd_help(args):
    lines = [
        f"  [{ACC}]list[/] [{MUTED}][--search X][/]                          List all subscriptions",
        f"  [{ACC}]stats[/] [{MUTED}]<id|comment>[/]                         Show detailed subscription info",
        f"  [{ACC}]create[/] [{MUTED}][--id X] --comment X [--note X] [--data GB] [--days N] [--firstuse-days N] [--firstuse-seconds N] [--ip N] [--nodes 1,2|all|none][/]",
        f"  [{ACC}]edit[/] [{MUTED}]<id|comment> [--data GB] [--days N] [--firstuse-days N] [--firstuse-seconds N] [--no-firstuse] [--remove-data GB] [--remove-days N] [--no-expire] [--comment X] [--note X] [--ip N] [--enable] [--disable][/]",
        f"  [{ACC}]regen[/] [{MUTED}]<id|comment>[/]                         Regenerate subscription nanoid",
        f"  [{ACC}]regen-uuid[/] [{MUTED}]<id|comment>[/]                    Regenerate VLESS/VMess UUID for a subscription",
        f"  [{ACC}]reset-traffic[/] [{MUTED}]<id|comment>[/]                 Reset traffic counters for a subscription",
        f"  [{ACC}]delete[/] [{MUTED}]<id|comment>[/]                         Delete subscription",
        f"  [{ACC}]nodes[/]                                       List nodes",
        f"  [{ACC}]addnode[/] [{MUTED}]--name X --addr http://host:port --user X --pass X --inbound N [--proxy http://...] [--multiplier N][/]",
        f"  [{ACC}]editnode[/] [{MUTED}]<id> [--name X] [--addr X] [--user X] [--pass X] [--proxy X] [--enable|--disable][/]  (enable/disable removes/recreates clients)",
        f"  [{ACC}]delnode[/] [{MUTED}]<id>[/]                                Delete node",
        f"  [{ACC}]subnodes[/] [{MUTED}][node_id][/]                          List sub-nodes",
        f"  [{ACC}]addsubnode[/] [{MUTED}]--node N --inbound N [--name X] [--multiplier N][/]",
        f"  [{ACC}]editsubnode[/] [{MUTED}]<id> [--name X] [--inbound N] [--multiplier N] [--enable|--disable] [--move-up] [--move-down][/]  (enable/disable removes/recreates clients)",
        f"  [{ACC}]delsubnode[/] [{MUTED}]<id>[/]                              Delete sub-node",
        f"  [{ACC}]bot[/] [{MUTED}][--enable|--disable][/]                    Show or toggle Telegram bot",
        f"  [{ACC}]configs[/] [{MUTED}]<id or comment>[/]                       Show per-node config URLs for a subscription",
        f"  [{ACC}]status[/]                                      System overview",
        f"  [{ACC}]update[/]                                      Check and apply update",
    ]
    console.print(Panel("\n".join(lines), title=f"[bold white]GhostGate CLI[/]  [{MUTED}]v{updater.VERSION}[/]", border_style=DIM, padding=(0, 1)))

def cmd_configs(args):
    if not args:
        console.print(f"[{DANGER}]Usage: ghostgate configs <id or comment>[/]")
        return
    identifier = " ".join(args)
    sub = db.get_sub(identifier) or db.get_sub_by_comment(identifier)
    if not sub:
        console.print(f"[{DANGER}]Subscription not found: {identifier}[/]")
        return
    from panel import _build_sub_configs
    configs = _build_sub_configs(sub["id"])
    if not configs:
        console.print(f"[{MUTED}]No configs available for this subscription.[/]")
        return
    lines = []
    for c in configs:
        lines.append(f"[bold white]{c['node']}[/]")
        lines.append(f"  [{ACC}]{c['config']}[/]")
    console.print(Panel("\n".join(lines), title=f"[bold white]Configs: {sub.get('comment') or sub['id']}[/]", border_style=DIM, padding=(0, 1)))

_COMMANDS = {
    "list": cmd_list,
    "stats": cmd_stats,
    "nodes": cmd_nodes,
    "addnode": cmd_addnode,
    "editnode": cmd_editnode,
    "delnode": cmd_delnode,
    "subnodes": cmd_subnodes,
    "listsubnode": cmd_subnodes,
    "status": cmd_status,
    "create": cmd_create,
    "delete": cmd_delete,
    "edit": cmd_edit,
    "regen": cmd_regen,
    "regen-uuid": cmd_regen_uuid,
    "reset-traffic": cmd_reset_traffic,
    "configs": cmd_configs,
    "addsubnode": cmd_addsubnode,
    "editsubnode": cmd_editsubnode,
    "delsubnode": cmd_delsubnode,
    "bot": cmd_bot,
    "update": cmd_update,
    "help": cmd_help,
}

def dispatch(command, args):
    env_path = os.getenv("ENV_PATH") or ("/opt/ghostgate/.env" if os.path.exists("/opt/ghostgate/.env") else ".env")
    load_dotenv(env_path)
    db.init_db()
    fn = _COMMANDS.get(command)
    if fn:
        fn(args)
    else:
        console.print(f"[{DANGER}]Unknown command: {command}[/]")
        cmd_help([])
