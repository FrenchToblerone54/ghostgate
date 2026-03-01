# GhostGate - VPN Subscription Panel

**[📖 فارسی / Persian](README_FA.md)**

GhostGate is a sales and subscription management panel for [3x-ui](https://github.com/MHSanaei/3x-ui) VPN panels. It provides a Telegram bot for managing subscriptions, a web admin panel, and automatic traffic synchronization across multiple nodes.

## Features

- **Multi-node support** - Manage subscriptions across multiple 3x-ui servers with shared data limits
- **Telegram bot** - Create, edit, delete, and monitor subscriptions via bot commands
- **Web admin panel** - Real-time system monitoring, subscription management, node management, logs
- **Auto sync** - Background worker syncs traffic usage and enforces data/expiry limits
- **Subscription links** - Standard VLESS and VMess subscription URLs with QR codes
- **External proxy support** - Respects 3x-ui external proxy configurations for CDN setups
- **Compiled binary** - Linux amd64 (Ubuntu 22.04+ compatible), no Python required on server
- **systemd service** - Automated start, restart, logging
- **Auto-update** - Automatic binary updates via GitHub releases; manual update via `ghostgate update` or the Settings page
- **Bulk operations** - Bulk delete, enable, or disable multiple subscriptions at once from the web panel
- **Easy installation** - One-command setup script with interactive configuration

## Quick Start

```bash
wget https://raw.githubusercontent.com/frenchtoblerone54/ghostgate/main/scripts/install.sh -O install.sh
chmod +x install.sh
sudo ./install.sh
```

Save the panel URL shown at the end — it is your admin panel access path.

## Bot Commands

```
/create [--comment Name] [--note X] [--data GB] [--days N] [--ip N] [--nodes 1,2|all|none]
/delete <id or comment>
/stats <id or comment>
/list [page]
/edit <id or comment> [--comment X] [--note X] [--data GB] [--days N] [--remove-data GB] [--remove-days N] [--no-expire] [--ip N] [--enable] [--disable]
/regen <id or comment>
/nodes
```

## Configuration

All settings are stored in `/opt/ghostgate/.env`. They can also be edited from the Settings page in the web panel (restart required for changes to take effect).

| Variable | Default | Description |
|---|---|---|
| `BASE_URL` | | Public URL of your server (e.g. `https://your-domain.com`) |
| `BOT_TOKEN` | | Telegram bot token from @BotFather |
| `ADMIN_ID` | | Your Telegram user ID |
| `PANEL_PATH` | auto-generated | Secret path for the web panel |
| `HOST` | `127.0.0.1` | Listen host |
| `PORT` | `5000` | Listen port |
| `SYNC_INTERVAL` | `20` | Traffic sync interval in seconds |
| `BOT_PROXY` | | HTTP proxy for Telegram bot (optional) |
| `UPDATE_PROXY` | | HTTP proxy for auto-updater (optional) |
| `DATA_LABEL` | `Data Usage` | Label for data section on subscription page |
| `EXPIRE_LABEL` | `Time Remaining` | Label for expiry section on subscription page |
| `PANEL_THREADS` | `8` | Waitress worker thread count |
| `DB_PATH` | `/opt/ghostgate/ghostgate.db` | SQLite database path |
| `LOG_FILE` | `/var/log/ghostgate.log` | Log file path |
| `AUTO_UPDATE` | `false` | Enable automatic binary updates |
| `UPDATE_CHECK_INTERVAL` | `300` | Seconds between update checks |

## REST API

The web panel exposes a REST API at `/{panel_path}/api/`. It is protected by the secret panel path — no separate authentication token is required. The same API is used by the web panel itself.

### Subscriptions

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/subscriptions` | List subscriptions. Query params: `page`, `per_page` (0 = all), `search`, `sort_by` (`used_bytes` or `expire_at`), `sort_dir` (`asc` or `desc`) |
| `GET` | `/api/subscriptions/stream` | SSE stream — emits only changed/deleted subscriptions every 5s |
| `POST` | `/api/subscriptions` | Create subscription and add to nodes. Body: `comment`, `note`, `data_gb`, `days`, `ip_limit`, `node_ids`, `show_multiplier`, `expire_after_first_use_seconds` |
| `GET` | `/api/subscriptions/<id>` | Get subscription with node list |
| `PUT` | `/api/subscriptions/<id>` | Update fields: `comment`, `note`, `data_gb`, `days`, `ip_limit`, `enabled`, `show_multiplier`, `expire_after_first_use_seconds`, `remove_days`, `remove_expiry`, `remove_data_limit` |
| `DELETE` | `/api/subscriptions/<id>` | Delete subscription and remove clients from all nodes |
| `GET` | `/api/subscriptions/<id>/stats` | Get traffic stats |
| `GET` | `/api/subscriptions/<id>/qr` | QR code PNG for the subscription link |
| `POST` | `/api/subscriptions/<id>/nodes` | Add node(s) to an existing subscription |
| `DELETE` | `/api/subscriptions/<id>/nodes/<node_id>` | Remove a node from a subscription |
| `POST` | `/api/subscriptions/<id>/regen-id` | Regenerate the subscription nanoid (updates XUI clients). Returns `{new_id, url}` |

**Create subscription — request body:**
```json
{
  "comment": "John Doe",
  "note": "Note shown in subscription (optional)",
  "data_gb": 10,
  "days": 30,
  "ip_limit": 2,
  "node_ids": [1, 2]
}
```

**Create subscription — response:**
```json
{
  "id": "abc123...",
  "uuid": "xxxxxxxx-...",
  "url": "https://your-domain.com/sub/abc123...",
  "errors": []
}
```

The `errors` array lists any nodes that failed to receive the client — the subscription is still created in the database.

### Nodes

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/nodes` | List all nodes (password omitted) |
| `POST` | `/api/nodes` | Add a node |
| `PUT` | `/api/nodes/<id>` | Update node fields |
| `DELETE` | `/api/nodes/<id>` | Delete a node |
| `GET` | `/api/nodes/<id>/test` | Test connection and inbound reachability |

**Add node — request body:**
```json
{
  "name": "Germany 1",
  "address": "http://1.2.3.4:54321",
  "username": "admin",
  "password": "secret",
  "inbound_id": 1,
  "proxy_url": null
}
```

**Add node(s) to subscription — request body:**
```json
{ "node_ids": [1, 2] }
```

Nodes already assigned to the subscription are silently skipped.

### Bulk Operations

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/bulk/nodes` | Add or remove a node across multiple subscriptions |
| `POST` | `/api/bulk/delete` | Delete multiple subscriptions and remove their clients from all nodes |
| `POST` | `/api/bulk/toggle` | Enable or disable multiple subscriptions |
| `POST` | `/api/bulk/extend` | Add data (GB) and/or days to multiple subscriptions |
| `POST` | `/api/bulk/note` | Set or clear the note on multiple subscriptions |

**`/api/bulk/nodes` request body:**
```json
{
  "sub_ids": ["abc123", "def456"],
  "node_ids": [1],
  "action": "add"
}
```

`action` is either `"add"` or `"remove"`. Returns `{"ok": true, "errors": [...]}`.

**`/api/bulk/delete` request body:**
```json
{ "sub_ids": ["abc123", "def456"] }
```

Returns `{"ok": true, "deleted": 2}`.

**`/api/bulk/toggle` request body:**
```json
{ "sub_ids": ["abc123", "def456"], "enabled": false }
```

Returns `{"ok": true}`.

**`/api/bulk/extend` request body:**
```json
{ "sub_ids": ["abc123", "def456"], "data_gb": 10, "days": 30 }
```

Both `data_gb` and `days` are optional and additive — data is added to the current limit, days are extended from the current expiry (or from now if no expiry is set). **Negative values subtract** — e.g. `"data_gb": -5` removes 5 GB (clamped to 0), `"days": -7` removes 7 days from the current expiry (skipped if no expiry set). Pass `"remove_expiry": true` to clear the expiry date (takes priority over `days`). Pass `"remove_data_limit": true` to set unlimited data (takes priority over `data_gb`). All expiry changes are pushed to 3x-ui nodes immediately. Returns `{"ok": true}`.

**`/api/bulk/note` request body:**
```json
{ "sub_ids": ["abc123", "def456"], "note": "Promo batch" }
```

Omit `note` or pass `null` to clear it. The note is emitted as a `vless://` info entry in each subscription. Returns `{"ok": true}`.

### Other

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/status` | System metrics (CPU, RAM, disk, network, load) |
| `GET` | `/api/update` | Check for a binary update. Returns `{current, latest, update_available}` |
| `POST` | `/api/update` | Download and apply the latest binary update, then restart |
| `GET` | `/api/settings` | Get all `.env` config values |
| `POST` | `/api/settings` | Save config values (restart required for most changes) |
| `POST` | `/api/restart` | Restart the GhostGate service |
| `GET` | `/api/logs` | Last 200 log lines (plain text) |
| `GET` | `/api/logs/stream` | Live log stream (SSE, sends `: heartbeat` every 10 s when idle) |

### Subscription Link

The end-user subscription URL is public and requires no authentication:

```
https://your-domain.com/sub/<id>
```

This returns a plain-text config list (VLESS and VMess) compatible with standard VPN clients.

## nginx Configuration

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
        proxy_buffering off;
    }
}
```

## systemd Management

```bash
sudo systemctl status ghostgate
sudo systemctl restart ghostgate
sudo systemctl stop ghostgate
sudo journalctl -u ghostgate -f
```

## CLI Commands

The CLI uses [rich](https://github.com/Textualize/rich) for colored terminal output matching the panel theme.

| Command | Description |
|---|---|
| `ghostgate` | Start the service (normal mode) |
| `ghostgate --version` | Print version and exit |
| `ghostgate --generate-path` | Generate a new random panel path and exit |
| `ghostgate help` | Show CLI help and available commands |
| `ghostgate status` | Show system status (CPU, RAM, disk, uptime) |
| `ghostgate list [--search X]` | List all subscriptions, with optional search filter |
| `ghostgate stats <id\|comment>` | Show traffic stats for a subscription |
| `ghostgate create --comment X [--note X] [--data GB] [--days N] [--ip N] [--nodes 1,2\|all\|none]` | Create a new subscription |
| `ghostgate edit <id\|comment> [--data GB] [--days N] [--remove-data GB] [--remove-days N] [--no-expire] [--comment X] [--note X] [--ip N] [--enable] [--disable]` | Edit an existing subscription |
| `ghostgate regen <id\|comment>` | Regenerate the subscription nanoid (old URL stops working) |
| `ghostgate delete <id\|comment>` | Delete a subscription and remove its clients from all nodes |
| `ghostgate nodes` | List all configured nodes |
| `ghostgate update` | Check for an update and apply it if available |

**Examples:**

```bash
ghostgate list
ghostgate list --search alice
ghostgate stats abc123
ghostgate create --comment "Alice" --data 50 --days 30 --ip 2 --nodes 1,2
ghostgate edit abc123 --data 100 --days 60
ghostgate edit abc123 --remove-data 5 --remove-days 7
ghostgate edit abc123 --disable
ghostgate regen abc123
ghostgate delete abc123
ghostgate nodes
ghostgate status
ghostgate update
ghostgate --version
ghostgate --generate-path
```

## Building from Source

```bash
pip install -r requirements.txt pyinstaller
./build/build.sh
```

Or using Docker (recommended for Ubuntu 22.04 GLIBC compatibility):

```bash
./build/build-docker.sh
```

Binary will be created in `dist/`.

## Community

Join the Telegram channel for updates and announcements: [@GhostSoftDev](https://t.me/GhostSoftDev)

## License

MIT License - See LICENSE file for details
