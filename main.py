import os
import sys
import argparse
import threading
import logging
from dotenv import load_dotenv
import updater

load_dotenv(os.getenv("ENV_PATH", ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("main")

def _migrate(old_db_path, node_id):
    import sqlite3
    import database as db
    if not db.get_node(node_id):
        print(f"Error: node {node_id} not found. Add it via the panel or bot first.")
        return
    conn = sqlite3.connect(old_db_path)
    conn.row_factory = sqlite3.Row
    configs = conn.execute("SELECT * FROM configs").fetchall()
    count = 0
    for cfg in configs:
        try:
            if db.get_sub(cfg["id"]):
                continue
            db.create_sub(comment=cfg["comment"], sub_id=cfg["id"])
            db.add_sub_node(cfg["id"], node_id, cfg["client_id"], cfg["id"])
            count += 1
        except Exception as e:
            print(f"migrate error {cfg['id']}: {e}", file=sys.stderr)
    conn.close()
    print(f"Migrated {count}/{len(configs)} subscriptions from {old_db_path}")

def main():
    parser = argparse.ArgumentParser(description="GhostGate - VPN Subscription Manager")
    parser.add_argument("--generate-path", action="store_true", help="Generate a new random panel path")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("--migrate-from", help=argparse.SUPPRESS)
    parser.add_argument("--migrate-node", type=int, default=1, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.version:
        print(f"ghostgate v{updater.VERSION}")
        sys.exit(0)

    if args.generate_path:
        from nanoid import generate
        print(generate(size=20))
        sys.exit(0)

    import database as db
    db.init_db()

    if args.migrate_from:
        _migrate(args.migrate_from, args.migrate_node)
        sys.exit(0)

    logging.getLogger().addHandler(
        logging.FileHandler(os.getenv("LOG_FILE", "/var/log/ghostgate.log"), delay=True)
    )

    panel_path = os.getenv("PANEL_PATH", "")
    if not panel_path:
        from nanoid import generate
        panel_path = generate(size=20)
        from dotenv import set_key
        env_path = os.getenv("ENV_PATH", ".env")
        set_key(env_path, "PANEL_PATH", panel_path)
        logger.info(f"Generated panel path: {panel_path}")

    import panel
    panel.register_routes(panel_path)

    sync_interval = int(os.getenv("SYNC_INTERVAL", "20"))
    import sync
    sync.start_sync(sync_interval)
    logger.info(f"Sync started (interval: {sync_interval}s)")

    updater.start_auto_update()
    logger.info(f"GhostGate v{updater.VERSION} started")

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))

    from waitress import serve

    def _run_flask():
        logger.info(f"Panel running at http://{host}:{port}/{panel_path}/")
        serve(panel.app, host=host, port=port, threads=8)

    flask_thread = threading.Thread(target=_run_flask, daemon=True)
    flask_thread.start()

    logger.info("Starting Telegram bot...")
    import bot
    bot.start()

if __name__ == "__main__":
    main()
