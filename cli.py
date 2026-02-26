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
    tbl = Table(box=box.ROUNDED, border_style=DIM, header_style=f"bold {MUTED}")
    tbl.add_column("#", style=MUTED)
    tbl.add_column("Name", style="bold white")
    tbl.add_column("Address", style=f"{BLUE}")
    tbl.add_column("Inbound", style=MUTED)
    tbl.add_column("Proxy", style=MUTED)
    tbl.add_column("×Mult", style=WARN)
    tbl.add_column("Status")
    for n in nodes:
        status = Text("● Enabled", style=ACC) if n.get("enabled") else Text("● Disabled", style=DANGER)
        mult = n.get("traffic_multiplier") or 1.0
        tbl.add_row(str(n["id"]), n["name"], n["address"], str(n["inbound_id"]),
            "Proxy" if n.get("proxy_url") else "—", f"×{mult:g}" if mult != 1.0 else "—", status)
    console.print(Panel(tbl, title=f"[bold white]Nodes[/]", border_style=DIM, padding=(0, 1)))

def cmd_status(args):
    subs, total = db.get_subs(page=1, per_page=0)
    now = datetime.now(timezone.utc)
    active = sum(1 for s in subs if s.get("enabled") != 0
        and not (s.get("expire_at") and datetime.fromisoformat(s["expire_at"]).replace(tzinfo=timezone.utc) < now)
        and not (s.get("data_gb", 0) > 0 and (s.get("used_bytes") or 0) >= int(s["data_gb"]*1073741824)))
    nodes = db.get_nodes()
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
        f"  [{MUTED}]Nodes[/]     [{MUTED}]{len(nodes)}[/]",
    ]
    console.print(Panel("\n".join(lines), title=f"[bold white]GhostGate[/]", border_style=DIM, padding=(0, 1)))

def cmd_create(args):
    from xui_client import XUIClient
    opts = _parse_opts(args)
    comment = opts.get("comment", "")
    data_gb = float(opts.get("data", opts.get("data-gb", 0)))
    days = int(opts.get("days", 0))
    firstuse_days = int(opts.get("firstuse-days", 0))
    firstuse_seconds = int(opts.get("firstuse-seconds", opts.get("firstuse", 0)))
    expire_after_first_use_seconds = max(0, firstuse_seconds or (firstuse_days * 86400))
    ip_limit = int(opts.get("ip", 0))
    show_multiplier = max(1, int(opts.get("show-multiplier", 1)))
    node_ids_raw = opts.get("nodes", "")
    all_nodes = db.get_nodes()
    if node_ids_raw == "all":
        node_ids = [n["id"] for n in all_nodes]
    elif node_ids_raw == "none" or not node_ids_raw:
        node_ids = []
    else:
        node_ids = [int(x) for x in node_ids_raw.split(",")]
    custom_id = opts.get("id") or None
    if custom_id and db.get_sub(custom_id):
        console.print(f"[{DANGER}]ID already exists: {custom_id}[/]")
        return
    sub_id = db.create_sub(comment=comment, data_gb=data_gb, days=days, ip_limit=ip_limit, show_multiplier=show_multiplier, sub_id=custom_id, expire_after_first_use_seconds=expire_after_first_use_seconds)
    sub = db.get_sub(sub_id)
    client_uuid = str(uuid.uuid4())
    expire_ms = 0
    if sub.get("expire_at"):
        try: expire_ms = int(datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp()*1000)
        except Exception: pass
    expiry_time = -expire_after_first_use_seconds*1000 if expire_after_first_use_seconds>0 and not sub.get("expire_at") else expire_ms
    errors = []
    for node_id in node_ids:
        node = db.get_node(node_id)
        if not node: continue
        try:
            xui = XUIClient(node["address"], node["username"], node["password"], node.get("proxy_url"))
            total_limit_bytes = int(data_gb * 1073741824 / (node.get("traffic_multiplier") or 1.0)) if data_gb > 0 else 0
            email = f"{sub_id}-{node_id}"
            client = xui.make_client(email, client_uuid, expiry_time, ip_limit, sub_id, comment, total_limit_bytes)
            ok = xui.add_client(node["inbound_id"], client)
            if ok: db.add_sub_node(sub_id, node_id, client_uuid, email)
            else: errors.append(f"node {node_id}: failed")
        except Exception as e:
            errors.append(f"node {node_id}: {e}")
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
        console.print(f"[{DANGER}]Usage: ghostgate edit <id or comment> [--data GB] [--days N] [--firstuse-days N] [--firstuse-seconds N] [--no-firstuse] [--comment X] [--ip N][/]")
        return
    key = pos[0]
    sub = db.get_sub(key) or db.get_sub_by_comment(key)
    if not sub:
        console.print(f"[{DANGER}]Not found: {key}[/]")
        return
    opts = _parse_opts(args[1:])
    updates = {}
    if "comment" in opts: updates["comment"] = opts["comment"]
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
        console.print(f"[{WARN}]Nothing to update. Use --data, --days, --remove-data, --remove-days, --no-expire, --comment, --ip, --enable, --disable[/]")
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
        f"  [{ACC}]create[/] [{MUTED}][--id X] --comment X [--data GB] [--days N] [--firstuse-days N] [--firstuse-seconds N] [--ip N] [--nodes 1,2|all|none][/]", 
        f"  [{ACC}]edit[/] [{MUTED}]<id|comment> [--data GB] [--days N] [--firstuse-days N] [--firstuse-seconds N] [--no-firstuse] [--remove-data GB] [--remove-days N] [--no-expire] [--comment X] [--ip N] [--enable] [--disable][/]", 
        f"  [{ACC}]delete[/] [{MUTED}]<id|comment>[/]                         Delete subscription",
        f"  [{ACC}]nodes[/]                                       List nodes",
        f"  [{ACC}]status[/]                                      System overview",
        f"  [{ACC}]update[/]                                      Check and apply update",
    ]
    console.print(Panel("\n".join(lines), title=f"[bold white]GhostGate CLI[/]  [{MUTED}]v{updater.VERSION}[/]", border_style=DIM, padding=(0, 1)))

_COMMANDS = {
    "list": cmd_list,
    "stats": cmd_stats,
    "nodes": cmd_nodes,
    "status": cmd_status,
    "create": cmd_create,
    "delete": cmd_delete,
    "edit": cmd_edit,
    "update": cmd_update,
    "help": cmd_help,
}

def dispatch(command, args):
    load_dotenv(os.getenv("ENV_PATH", ".env"))
    db.init_db()
    fn = _COMMANDS.get(command)
    if fn:
        fn(args)
    else:
        console.print(f"[{DANGER}]Unknown command: {command}[/]")
        cmd_help([])
