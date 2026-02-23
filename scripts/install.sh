#!/bin/bash
set -e

GITHUB_REPO="frenchtoblerone54/ghostgate"
VERSION="latest"

echo "GhostGate Installation"
echo "======================"

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ]; then
    echo "Error: Only x86_64 (amd64) architecture is supported"
    exit 1
fi

OS=$(uname -s)
if [ "$OS" != "Linux" ]; then
    echo "Error: Only Linux is supported"
    exit 1
fi

echo "Downloading GhostGate..."
wget -q --show-progress "https://github.com/${GITHUB_REPO}/releases/${VERSION}/download/ghostgate" -O /tmp/ghostgate
wget -q "https://github.com/${GITHUB_REPO}/releases/${VERSION}/download/ghostgate.sha256" -O /tmp/ghostgate.sha256

echo "Verifying checksum..."
cd /tmp
sha256sum -c ghostgate.sha256

echo "Installing binary..."
install -m 755 /tmp/ghostgate /usr/local/bin/ghostgate

echo "Creating configuration directory..."
mkdir -p /opt/ghostgate

if [ ! -f /opt/ghostgate/.env ]; then
    echo ""
    echo "Configuration"
    echo "-------------"

    PANEL_PATH=$(/usr/local/bin/ghostgate --generate-path)

    read -p "Base URL (e.g. https://your-domain.com): " BASE_URL
    BASE_URL=${BASE_URL:-"http://localhost:5000"}

    echo ""
    echo "Telegram Bot Setup"
    read -p "Bot Token (from @BotFather): " BOT_TOKEN
    read -p "Admin Telegram User ID: " ADMIN_ID

    echo ""
    echo "Server Settings"
    read -p "Listen host [127.0.0.1]: " HOST
    HOST=${HOST:-127.0.0.1}
    read -p "Listen port [5000]: " PORT
    PORT=${PORT:-5000}
    read -p "Sync interval seconds [20]: " SYNC_INTERVAL
    SYNC_INTERVAL=${SYNC_INTERVAL:-20}

    echo ""
    read -p "Bot proxy URL (leave empty if not needed): " BOT_PROXY

    echo ""
    read -p "Enable auto-update? [Y/n]: " AUTO_UPDATE_INPUT
    AUTO_UPDATE_INPUT=${AUTO_UPDATE_INPUT:-y}
    if [[ $AUTO_UPDATE_INPUT =~ ^[Yy]$ ]]; then
        AUTO_UPDATE="true"
    else
        AUTO_UPDATE="false"
    fi

    touch /var/log/ghostgate.log

    cat > /opt/ghostgate/.env <<EOF
BASE_URL=${BASE_URL}
BOT_TOKEN=${BOT_TOKEN}
ADMIN_ID=${ADMIN_ID}
PANEL_PATH=${PANEL_PATH}
HOST=${HOST}
PORT=${PORT}
SYNC_INTERVAL=${SYNC_INTERVAL}
BOT_PROXY=${BOT_PROXY}
DB_PATH=/opt/ghostgate/ghostgate.db
LOG_FILE=/var/log/ghostgate.log
ENV_PATH=/opt/ghostgate/.env
AUTO_UPDATE=${AUTO_UPDATE}
UPDATE_CHECK_INTERVAL=3600
EOF

    chmod 600 /opt/ghostgate/.env
else
    echo "Configuration already exists at /opt/ghostgate/.env"
    HOST=$(grep "^HOST=" /opt/ghostgate/.env | cut -d'=' -f2)
    PORT=$(grep "^PORT=" /opt/ghostgate/.env | cut -d'=' -f2)
    PANEL_PATH=$(grep "^PANEL_PATH=" /opt/ghostgate/.env | cut -d'=' -f2)
    BASE_URL=$(grep "^BASE_URL=" /opt/ghostgate/.env | cut -d'=' -f2)
    HOST=${HOST:-127.0.0.1}
    PORT=${PORT:-5000}
fi

echo "Installing systemd service..."
cat > /etc/systemd/system/ghostgate.service <<EOF
[Unit]
Description=GhostGate VPN Subscription Manager
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ghostgate
Restart=always
RestartSec=5
EnvironmentFile=/opt/ghostgate/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

read -p "Configure nginx with TLS? [y/N]: " -n 1 -r SETUP_NGINX
echo
if [[ $SETUP_NGINX =~ ^[Yy]$ ]]; then
    apt-get update -qq && apt-get install -y -qq nginx certbot python3-certbot-nginx

    if [ -f /etc/nginx/sites-available/ghostgate ]; then
        rm -f /etc/nginx/sites-enabled/ghostgate /etc/nginx/sites-available/ghostgate
        systemctl is-active --quiet nginx && systemctl reload nginx
    fi

    read -p "Domain name: " DOMAIN

    cat > /etc/nginx/sites-available/ghostgate <<EOF
server {
    listen 80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/ghostgate /etc/nginx/sites-enabled/
    nginx -t && systemctl reload nginx

    read -p "Generate TLS certificate with Let's Encrypt? [Y/n]: " -n 1 -r TLS
    echo
    if [[ ! $TLS =~ ^[Nn]$ ]]; then
        certbot --nginx -d "${DOMAIN}"
    fi

    cat > /etc/nginx/sites-available/ghostgate <<EOF
server {
    listen 80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    location / {
        return 301 https://\$server_name\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://${HOST}:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
        proxy_buffering off;
    }
}
EOF

    nginx -t && systemctl reload nginx
    echo "nginx configured for ${DOMAIN}"
fi

echo "Enabling and starting GhostGate..."
systemctl enable ghostgate
if systemctl is-active --quiet ghostgate; then
    systemctl restart ghostgate
else
    systemctl start ghostgate
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║               GhostGate Installation Complete             ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                            ║"
echo "║  Panel URL:                                                ║"
echo "║  ${BASE_URL}/${PANEL_PATH}/                               "
echo "║                                                            ║"
echo "║  ⚠  Save this URL! It is your admin panel access path.   ║"
echo "║                                                            ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Useful commands:                                          ║"
echo "║  sudo systemctl status ghostgate                          ║"
echo "║  sudo systemctl restart ghostgate                         ║"
echo "║  sudo journalctl -u ghostgate -f                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
