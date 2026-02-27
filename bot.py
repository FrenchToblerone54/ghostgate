import os
import asyncio
import logging
import time
import uuid
import shlex
import io
import html as _html
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import qrcode
import database as db
from xui_client import XUIClient

logger = logging.getLogger("bot")

def _is_admin(user_id):
    admin = os.getenv("ADMIN_ID", "").strip()
    if str(user_id) != admin:
        logger.warning(f"unauthorized access attempt from user_id={user_id} (expected {admin!r})")
        return False
    return True

def _parse_opts(args):
    opts = {}
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            key = args[i][2:]
            val = args[i+1] if i+1 < len(args) and not args[i+1].startswith("--") else "true"
            opts[key] = val
            i += 2 if val != "true" else 1
        else:
            i += 1
    return opts

def _make_qr_bytes(text):
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#00e5a0", back_color="#1a1d2e")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

def _fmt_bytes(b):
    if b < 1073741824:
        return f"{b/1048576:.2f} MB"
    return f"{b/1073741824:.2f} GB"

def _sub_url(sub_id):
    base = os.getenv("BASE_URL", "").rstrip("/")
    return f"{base}/sub/{sub_id}"

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "GhostGate Bot\n\n"
        "/create [--comment X] [--data GB] [--days N] [--firstuse-days N] [--firstuse-seconds N] [--ip N] [--nodes 1,2|all|none]\n"
        "/delete <id or comment>\n"
        "/stats <id or comment>\n"
        "/edit <id or comment> [--comment X] [--data GB] [--days N] [--firstuse-days N] [--firstuse-seconds N] [--no-firstuse] [--remove-data GB] [--remove-days N] [--no-expire] [--ip N] [--enable] [--disable]\n"
        "/regen <id or comment>\n"
        "/list [page] — 10 per page\n"
        "/nodes\n"
        "/addnode --name X --addr http://... --user X --pass X --inbound N [--proxy http://...] [--multiplier N]\n"
        "/delnode <id>\n"
        "/subnodes [node_id]\n"
        "/addsubnode --node N --inbound N [--name X] [--multiplier N]\n"
        "/editsubnode <id> [--name X] [--inbound N] [--multiplier N] [--enable|--disable]\n"
        "/delsubnode <id>\n"
    )

async def cmd_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    try:
        args = shlex.split(" ".join(ctx.args or []))
    except Exception:
        args = ctx.args or []
    opts = _parse_opts(args)
    comment = opts.get("comment")
    data_gb = float(opts.get("data", 0))
    days = int(opts.get("days", 0))
    firstuse_days = int(opts.get("firstuse-days", 0))
    firstuse_seconds = int(opts.get("firstuse-seconds", opts.get("firstuse", 0)))
    expire_after_first_use_seconds = max(0, firstuse_seconds or (firstuse_days * 86400))
    ip_limit = int(opts.get("ip", 0))
    show_multiplier = max(1, int(opts.get("show-multiplier", 1)))
    nodes_str = opts.get("nodes", "all")
    all_inbounds = db.get_all_node_inbounds()
    if not all_inbounds:
        await update.message.reply_text("No sub-nodes configured. Add nodes and sub-nodes via the web panel first.")
        return
    if nodes_str == "all":
        node_ids = [ni["id"] for ni in all_inbounds if ni.get("enabled") and ni.get("node_enabled")]
    elif nodes_str == "none":
        node_ids = []
    else:
        node_ids = [int(x.strip()) for x in nodes_str.split(",") if x.strip().isdigit()]
    sub_id = db.create_sub(comment=comment, data_gb=data_gb, days=days, ip_limit=ip_limit, show_multiplier=show_multiplier, expire_after_first_use_seconds=expire_after_first_use_seconds)
    sub = db.get_sub(sub_id)
    client_uuid = str(uuid.uuid4())
    expire_ms = 0
    if sub.get("expire_at"):
        try:
            expire_ms = int(datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except Exception:
            pass
    expiry_time = -expire_after_first_use_seconds*1000 if expire_after_first_use_seconds>0 and not sub.get("expire_at") else expire_ms
    added_nodes = []
    for node_id in node_ids:
        ni = db.get_node_inbound_with_node(node_id)
        if not ni:
            continue
        try:
            xui = XUIClient(ni["address"], ni["username"], ni["password"], ni.get("proxy_url"))
            total_limit_bytes = int(data_gb * 1073741824 / (ni.get("traffic_multiplier") or 1.0)) if data_gb > 0 else 0
            email = f"{sub_id}-{node_id}"
            client = xui.make_client(email, client_uuid, expiry_time, ip_limit, sub_id, comment or "", total_limit_bytes)
            if xui.add_client(ni["inbound_id"], client):
                db.add_sub_node(sub_id, node_id, client_uuid, email)
                added_nodes.append(ni.get("inbound_name") or ni["name"])
        except Exception as e:
            logger.warning(f"create sub inbound {node_id} error: {e}")
    sub_link = _sub_url(sub_id)
    expire_str = sub["expire_at"][:10] if sub.get("expire_at") else "Never"
    data_str = f"{data_gb} GB" if data_gb > 0 else "Unlimited"
    nodes_str_out = ", ".join(added_nodes) if added_nodes else "None"
    msg = (
        f"Subscription Created\n\n"
        f"ID: <tg-spoiler>{_html.escape(sub_id)}</tg-spoiler>\n"
        f"Comment: {_html.escape(comment or '-')}\n"
        f"Data: {data_str}\n"
        f"Expires: {expire_str}\n"
        f"IP Limit: {ip_limit or 'Unlimited'}\n"
        f"Nodes: {_html.escape(nodes_str_out)}\n"
        + (f"Show ×{show_multiplier}\n" if show_multiplier > 1 else "")
        + f"\nLink: <tg-spoiler>{_html.escape(sub_link)}</tg-spoiler>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")
    qr_buf = _make_qr_bytes(sub_link)
    await update.message.reply_photo(photo=qr_buf, caption=f"QR: {comment or sub_id}")

async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /delete <id or comment>")
        return
    identifier = " ".join(ctx.args)
    sub = db.get_sub(identifier) or db.get_sub_by_comment(identifier)
    if not sub:
        await update.message.reply_text("Subscription not found.")
        return
    snodes = db.get_sub_nodes(sub["id"])
    for sn in snodes:
        try:
            xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
            xui.delete_client(sn["inbound_id"], sn["client_uuid"])
        except Exception:
            pass
    db.delete_sub(sub["id"])
    await update.message.reply_text(f"Deleted: {sub.get('comment') or sub['id']}")

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /stats <id or comment>")
        return
    identifier = " ".join(ctx.args)
    stats = db.get_stats(identifier)
    if not stats:
        sub = db.get_sub_by_comment(identifier)
        stats = db.get_stats(sub["id"]) if sub else None
    if not stats:
        await update.message.reply_text("Subscription not found.")
        return
    used = _fmt_bytes(stats.get("used_bytes") or 0)
    total = f"{stats['data_gb']} GB" if stats["data_gb"] > 0 else "Unlimited"
    expire = stats["expire_at"][:10] if stats.get("expire_at") else "Never"
    nodes = ", ".join(stats.get("nodes") or []) or "None"
    sm = stats.get("show_multiplier") or 1
    msg = (
        f"Stats: {stats.get('comment') or stats['id']}\n\n"
        f"Data: {used} / {total}\n"
        f"Expires: {expire}\n"
        f"IP Limit: {stats['ip_limit'] or 'Unlimited'}\n"
        f"Nodes: {nodes}\n"
        + (f"Show ×{sm}\n" if sm > 1 else "")
        + f"Accesses: {stats['access_count']}\n"
        f"First: {stats.get('first_access') or '-'}\n"
        f"Last: {stats.get('last_access') or '-'}"
    )
    await update.message.reply_text(msg)

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    page = int(ctx.args[0]) if ctx.args else 1
    subs, total = db.get_subs(page=page, per_page=10)
    if not subs:
        await update.message.reply_text("No subscriptions found.")
        return
    pages = (total + 9) // 10
    lines = [f"Subscriptions (page {page}/{pages}, total {total})\n"]
    for sub in subs:
        used = _fmt_bytes(sub.get("used_bytes") or 0)
        total_data = f"{sub['data_gb']} GB" if sub["data_gb"] > 0 else "Unlimited"
        expire = sub["expire_at"][:10] if sub.get("expire_at") else "Never"
        lines.append(f"{sub.get('comment') or '-'} | {used}/{total_data} | exp:{expire}")
    if page < pages:
        lines.append(f"\nNext page: /list {page+1}")
    await update.message.reply_text("\n".join(lines))

async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /edit <id or comment> [--comment X] [--data GB] [--days N] [--ip N]")
        return
    try:
        all_args = shlex.split(" ".join(ctx.args))
    except Exception:
        all_args = ctx.args
    identifier = all_args[0]
    opts = _parse_opts(all_args[1:])
    sub = db.get_sub(identifier) or db.get_sub_by_comment(identifier)
    if not sub:
        await update.message.reply_text("Subscription not found.")
        return
    updates = {}
    if "comment" in opts:
        updates["comment"] = opts["comment"]
    if "data" in opts:
        updates["data_gb"] = float(opts["data"])
    if "days" in opts:
        updates["days"] = int(opts["days"])
    if "firstuse-days" in opts or "firstuse-seconds" in opts or "firstuse" in opts:
        firstuse_days = int(opts.get("firstuse-days", 0))
        firstuse_seconds = int(opts.get("firstuse-seconds", opts.get("firstuse", 0)))
        updates["expire_after_first_use_seconds"] = max(0, firstuse_seconds or (firstuse_days * 86400))
        updates["expire_at"] = None
    if "no-firstuse" in opts:
        updates["expire_after_first_use_seconds"] = 0
    if "ip" in opts:
        updates["ip_limit"] = int(opts["ip"])
    if "show-multiplier" in opts:
        updates["show_multiplier"] = max(1, int(opts["show-multiplier"]))
    if "enable" in opts:
        updates["enabled"] = 1
    if "disable" in opts:
        updates["enabled"] = 0
    if "remove-data" in opts:
        updates["data_gb"] = max(0, (sub.get("data_gb") or 0) - float(opts["remove-data"]))
    if "no-expire" in opts:
        updates["expire_at"] = None
    elif "remove-days" in opts and sub.get("expire_at"):
        try:
            updates["expire_at"] = (datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc) - timedelta(days=int(opts["remove-days"]))).isoformat()
        except Exception:
            pass
    if updates:
        if updates.get("enabled") == 1:
            db.reset_sub_node_disabled(sub["id"])
        db.update_sub(sub["id"], **updates)
    await update.message.reply_text(f"Updated: {sub.get('comment') or sub['id']}")

async def cmd_addnode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    try:
        args = shlex.split(" ".join(ctx.args or []))
    except Exception:
        args = ctx.args or []
    opts = _parse_opts(args)
    name = opts.get("name")
    addr = opts.get("addr")
    user = opts.get("user")
    pwd = opts.get("pass")
    inbound = int(opts.get("inbound", 1))
    proxy = opts.get("proxy")
    multiplier = max(1.0, float(opts.get("multiplier", 1.0)))
    if not all([name, addr, user, pwd]):
        await update.message.reply_text("Usage: /addnode --name X --addr http://host:port --user X --pass X --inbound N [--proxy http://...] [--multiplier N]")
        return
    node_id = db.add_node(name, addr, user, pwd, proxy)
    ni_id = db.add_node_inbound(node_id, inbound, name, multiplier)
    mult_str = f" ×{multiplier:g}" if multiplier != 1.0 else ""
    await update.message.reply_text(f"Node added: [{node_id}] {name}{mult_str}\n{addr} — sub-node [{ni_id}] inbound {inbound}")

async def cmd_delnode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /delnode <id>")
        return
    try:
        node_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Node ID must be a number.")
        return
    node = db.get_node(node_id)
    if not node:
        await update.message.reply_text("Node not found.")
        return
    db.delete_node(node_id)
    await update.message.reply_text(f"Deleted node: [{node_id}] {node['name']}")

async def cmd_addsubnode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    try:
        args=shlex.split(" ".join(ctx.args or []))
    except Exception:
        args=ctx.args or []
    opts=_parse_opts(args)
    if not all(k in opts for k in ["node","inbound"]):
        await update.message.reply_text("Usage: /addsubnode --node <node_id> --inbound <id> [--name X] [--multiplier N]")
        return
    try:
        node_id=int(opts.get("node",0))
        inbound_id=int(opts.get("inbound",0))
        multiplier=max(1.0,float(opts.get("multiplier",1.0)))
    except ValueError:
        await update.message.reply_text("Node ID, inbound ID, and multiplier must be numbers.")
        return
    if node_id<=0 or inbound_id<=0:
        await update.message.reply_text("Node ID and inbound ID must be greater than 0.")
        return
    node=db.get_node(node_id)
    if not node:
        await update.message.reply_text("Node not found.")
        return
    ni_id=db.add_node_inbound(node_id,inbound_id,opts.get("name"),multiplier)
    mult_str=f" ×{multiplier:g}" if multiplier!=1.0 else ""
    label=opts.get("name") or f"Inbound {inbound_id}"
    await update.message.reply_text(f"Sub-node added: [{ni_id}] {label}{mult_str}\nNode: [{node_id}] {node['name']}")

async def cmd_delsubnode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /delsubnode <subnode_id>")
        return
    try:
        ni_id=int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Sub-node ID must be a number.")
        return
    ni=db.get_node_inbound_with_node(ni_id)
    if not ni:
        await update.message.reply_text("Sub-node not found.")
        return
    db.delete_node_inbound(ni_id)
    await update.message.reply_text(f"Deleted sub-node: [{ni_id}] {ni.get('inbound_name') or ni['name']} (inbound {ni['inbound_id']})")

async def cmd_editsubnode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /editsubnode <subnode_id> [--name X] [--inbound N] [--multiplier N] [--enable] [--disable]")
        return
    try:
        all_args=shlex.split(" ".join(ctx.args))
    except Exception:
        all_args=ctx.args
    try:
        ni_id=int(all_args[0])
    except ValueError:
        await update.message.reply_text("Sub-node ID must be a number.")
        return
    ni=db.get_node_inbound(ni_id)
    if not ni:
        await update.message.reply_text("Sub-node not found.")
        return
    opts=_parse_opts(all_args[1:])
    updates={}
    if "name" in opts:
        updates["name"]=opts["name"]
    if "inbound" in opts:
        try:
            updates["inbound_id"]=int(opts["inbound"])
        except ValueError:
            await update.message.reply_text("Inbound ID must be a number.")
            return
    if "multiplier" in opts:
        try:
            updates["traffic_multiplier"]=max(1.0,float(opts["multiplier"]))
        except ValueError:
            await update.message.reply_text("Multiplier must be a number.")
            return
    if "enable" in opts:
        updates["enabled"]=1
    if "disable" in opts:
        updates["enabled"]=0
    if not updates:
        await update.message.reply_text("No valid changes provided.")
        return
    db.update_node_inbound(ni_id,**updates)
    updated=db.get_node_inbound_with_node(ni_id)
    st="on" if updated and updated.get("inbound_enabled") else "off"
    mult=(updated.get("traffic_multiplier") if updated else ni.get("traffic_multiplier",1.0)) or 1.0
    mult_str=f" ×{mult:g}" if mult!=1.0 else ""
    name=(updated.get("inbound_name") if updated else ni.get("name")) or f"Inbound {(updated.get('inbound_id') if updated else ni.get('inbound_id'))}"
    inbound_id=updated.get("inbound_id") if updated else ni.get("inbound_id")
    await update.message.reply_text(f"Updated sub-node: [{ni_id}] {name}{mult_str}\nInbound: {inbound_id} ({st})")

async def cmd_subnodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if ctx.args:
        try:
            node_id=int(ctx.args[0])
        except ValueError:
            await update.message.reply_text("Usage: /subnodes [node_id]")
            return
        node=db.get_node(node_id)
        if not node:
            await update.message.reply_text("Node not found.")
            return
        inbounds=db.get_node_inbounds(node_id)
        if not inbounds:
            await update.message.reply_text(f"No sub-nodes for node [{node_id}] {node['name']}.")
            return
        lines=[f"Sub-nodes for [{node_id}] {node['name']}:\n"]
        for ni in inbounds:
            ni_status="on" if ni.get("enabled") else "off"
            mult=ni.get("traffic_multiplier") or 1.0
            mult_str=f" ×{mult:g}" if mult!=1.0 else ""
            lines.append(f"[{ni['id']}] {ni['name'] or 'Inbound '+str(ni['inbound_id'])} — ID:{ni['inbound_id']}{mult_str} ({ni_status})")
        await update.message.reply_text("\n".join(lines))
        return
    nodes=db.get_nodes()
    if not nodes:
        await update.message.reply_text("No nodes configured.")
        return
    lines=["Sub-nodes:\n"]
    has_any=False
    for n in nodes:
        inbounds=db.get_node_inbounds(n["id"])
        if not inbounds:
            continue
        has_any=True
        lines.append(f"[{n['id']}] {n['name']}")
        for ni in inbounds:
            ni_status="on" if ni.get("enabled") else "off"
            mult=ni.get("traffic_multiplier") or 1.0
            mult_str=f" ×{mult:g}" if mult!=1.0 else ""
            lines.append(f"  └─ [{ni['id']}] {ni['name'] or 'Inbound '+str(ni['inbound_id'])} — ID:{ni['inbound_id']}{mult_str} ({ni_status})")
    if not has_any:
        await update.message.reply_text("No sub-nodes configured.")
        return
    await update.message.reply_text("\n".join(lines))

async def cmd_regen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /regen <id or comment>")
        return
    from nanoid import generate
    identifier = " ".join(ctx.args)
    sub = db.get_sub(identifier) or db.get_sub_by_comment(identifier)
    if not sub:
        await update.message.reply_text("Subscription not found.")
        return
    new_id = generate(size=20)
    snodes = db.get_sub_nodes(sub["id"])
    for sn in snodes:
        try:
            xui = XUIClient(sn["address"], sn["username"], sn["password"], sn.get("proxy_url"))
            xui.update_client_email_subid(sn["inbound_id"], sn["client_uuid"], sn["email"], f"{new_id}-{sn['node_id']}", new_id)
        except Exception:
            pass
    db.rename_sub(sub["id"], new_id)
    new_link = _sub_url(new_id)
    msg = (f"ID Regenerated\n\nOld: <tg-spoiler>{_html.escape(sub['id'])}</tg-spoiler>\nNew: <tg-spoiler>{_html.escape(new_id)}</tg-spoiler>\nLink: <tg-spoiler>{_html.escape(new_link)}</tg-spoiler>")
    await update.message.reply_text(msg, parse_mode="HTML")
    qr_buf = _make_qr_bytes(new_link)
    await update.message.reply_photo(photo=qr_buf, caption=f"QR: {sub.get('comment') or new_id}")

async def cmd_nodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    nodes = db.get_nodes()
    if not nodes:
        await update.message.reply_text("No nodes configured.")
        return
    lines = ["Nodes:\n"]
    for n in nodes:
        status = "on" if n["enabled"] else "off"
        lines.append(f"[{n['id']}] {n['name']} — {n['address']} ({status})")
        for ni in db.get_node_inbounds(n["id"]):
            ni_status = "on" if ni["enabled"] else "off"
            mult = ni.get("traffic_multiplier") or 1.0
            mult_str = f" ×{mult:g}" if mult != 1.0 else ""
            lines.append(f"  └─ [{ni['id']}] {ni['name'] or 'Inbound '+str(ni['inbound_id'])} — ID:{ni['inbound_id']}{mult_str} ({ni_status})")
    await update.message.reply_text("\n".join(lines))

async def _error_handler(update, ctx):
    logger.error(f"bot error: {ctx.error}", exc_info=ctx.error)

async def _post_init(app):
    await app.bot.set_my_commands([
        ("start", "Show help"),
        ("create", "Create subscription"),
        ("delete", "Delete subscription"),
        ("stats", "Subscription stats"),
        ("list", "List subscriptions (10/page)"),
        ("edit", "Edit subscription"),
        ("regen", "Regenerate subscription nanoid"),
        ("nodes", "List nodes"),
        ("addnode", "Add a node"),
        ("delnode", "Delete a node"),
        ("subnodes", "List sub-nodes"),
        ("addsubnode", "Add sub-node"),
        ("editsubnode", "Edit sub-node"),
        ("delsubnode", "Delete sub-node"),
    ])

def _build_app():
    token = os.getenv("BOT_TOKEN", "")
    proxy = os.getenv("BOT_PROXY", "")
    builder = ApplicationBuilder().token(token)
    builder = builder.connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0).pool_timeout(30.0).post_init(_post_init)
    if proxy:
        builder = builder.proxy(proxy).get_updates_proxy(proxy)
    application = builder.build()
    application.add_error_handler(_error_handler)
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_start))
    application.add_handler(CommandHandler("create", cmd_create))
    application.add_handler(CommandHandler("delete", cmd_delete))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("list", cmd_list))
    application.add_handler(CommandHandler("edit", cmd_edit))
    application.add_handler(CommandHandler("regen", cmd_regen))
    application.add_handler(CommandHandler("nodes", cmd_nodes))
    application.add_handler(CommandHandler("addnode", cmd_addnode))
    application.add_handler(CommandHandler("delnode", cmd_delnode))
    application.add_handler(CommandHandler("subnodes", cmd_subnodes))
    application.add_handler(CommandHandler("listsubnode", cmd_subnodes))
    application.add_handler(CommandHandler("addsubnode", cmd_addsubnode))
    application.add_handler(CommandHandler("editsubnode", cmd_editsubnode))
    application.add_handler(CommandHandler("delsubnode", cmd_delsubnode))
    return application

async def _run_once():
    app = _build_app()
    async def _safe_wait(coro, timeout, name):
        try:
            await asyncio.wait_for(coro, timeout=timeout)
        except Exception as e:
            logger.warning(f"{name} failed/timed out: {e}")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        watchdog_task = None
        idle_task = None
        async def _watchdog():
            fails = 0
            while True:
                await asyncio.sleep(30)
                polling_task = getattr(app.updater, "_Updater__polling_task", None)
                if not app.updater.running or polling_task is None or polling_task.done():
                    raise RuntimeError("bot updater polling task stopped")
                try:
                    await asyncio.wait_for(app.bot.get_me(), timeout=10)
                    fails = 0
                except Exception as e:
                    fails += 1
                    logger.warning(f"bot watchdog failed ({fails}/3): {e}")
                    if fails >= 3:
                        raise RuntimeError("bot watchdog restart")
        try:
            watchdog_task = asyncio.create_task(_watchdog())
            idle_task = asyncio.create_task(asyncio.sleep(float("inf")))
            done, _ = await asyncio.wait({watchdog_task, idle_task}, return_when=asyncio.FIRST_EXCEPTION)
            for t in done:
                exc = t.exception()
                if exc:
                    raise exc
        finally:
            if watchdog_task and not watchdog_task.done():
                watchdog_task.cancel()
            if idle_task and not idle_task.done():
                idle_task.cancel()
            await _safe_wait(app.updater.stop(), 15, "bot updater.stop")
            await _safe_wait(app.stop(), 15, "bot app.stop")

def start():
    while True:
        try:
            asyncio.run(_run_once())
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            logger.error(f"bot crashed: {e}, restarting in 5s")
            time.sleep(5)
