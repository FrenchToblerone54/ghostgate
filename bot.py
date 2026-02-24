import os
import logging
import time
import uuid
import shlex
import io
import html as _html
from datetime import datetime, timezone
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
        "/create [--comment X] [--data GB] [--days N] [--ip N] [--nodes 1,2]\n"
        "/delete <id or comment>\n"
        "/stats <id or comment>\n"
        "/edit <id or comment> [--comment X] [--data GB] [--days N] [--ip N]\n"
        "/list [page]\n"
        "/nodes\n"
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
    ip_limit = int(opts.get("ip", 0))
    nodes_str = opts.get("nodes", "all")
    all_nodes = db.get_nodes()
    if not all_nodes:
        await update.message.reply_text("No nodes configured. Add nodes via the web panel first.")
        return
    if nodes_str == "all":
        node_ids = [n["id"] for n in all_nodes if n["enabled"]]
    elif nodes_str == "none":
        node_ids = []
    else:
        node_ids = [int(x.strip()) for x in nodes_str.split(",") if x.strip().isdigit()]
    sub_id = db.create_sub(comment=comment, data_gb=data_gb, days=days, ip_limit=ip_limit)
    sub = db.get_sub(sub_id)
    client_uuid = str(uuid.uuid4())
    expire_ms = 0
    if sub.get("expire_at"):
        try:
            expire_ms = int(datetime.fromisoformat(sub["expire_at"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except Exception:
            pass
    added_nodes = []
    for node_id in node_ids:
        node = db.get_node(node_id)
        if not node:
            continue
        try:
            xui = XUIClient(node["address"], node["username"], node["password"], node.get("proxy_url"))
            client = xui.make_client(sub_id, client_uuid, expire_ms, ip_limit, sub_id, comment or "")
            if xui.add_client(node["inbound_id"], client):
                db.add_sub_node(sub_id, node_id, client_uuid, sub_id)
                added_nodes.append(node["name"])
        except Exception as e:
            logger.warning(f"create sub node {node_id} error: {e}")
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
        f"Nodes: {_html.escape(nodes_str_out)}\n\n"
        f"Link: <tg-spoiler>{_html.escape(sub_link)}</tg-spoiler>"
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
    msg = (
        f"Stats: {stats.get('comment') or stats['id']}\n\n"
        f"Data: {used} / {total}\n"
        f"Expires: {expire}\n"
        f"IP Limit: {stats['ip_limit'] or 'Unlimited'}\n"
        f"Nodes: {nodes}\n"
        f"Accesses: {stats['access_count']}\n"
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
    if "ip" in opts:
        updates["ip_limit"] = int(opts["ip"])
    if updates:
        db.update_sub(sub["id"], **updates)
    await update.message.reply_text(f"Updated: {sub.get('comment') or sub['id']}")

async def cmd_nodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    nodes = db.get_nodes()
    if not nodes:
        await update.message.reply_text("No nodes configured.")
        return
    lines = ["Nodes:\n"]
    for n in nodes:
        status = "enabled" if n["enabled"] else "disabled"
        lines.append(f"[{n['id']}] {n['name']} - {n['address']} - inbound:{n['inbound_id']} - {status}")
    await update.message.reply_text("\n".join(lines))

async def _error_handler(update, ctx):
    logger.error(f"bot error: {ctx.error}", exc_info=ctx.error)

def _build_app():
    token = os.getenv("BOT_TOKEN", "")
    proxy = os.getenv("BOT_PROXY", "")
    builder = ApplicationBuilder().token(token)
    builder = builder.connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0).pool_timeout(30.0)
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
    application.add_handler(CommandHandler("nodes", cmd_nodes))
    return application

def start():
    while True:
        try:
            application = _build_app()
            application.run_polling(drop_pending_updates=True)
        except Exception as e:
            logger.error(f"bot crashed: {e}, restarting in 5s")
            time.sleep(5)
