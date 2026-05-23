#!/bin/bash
set -euo pipefail

# ============================================================
# Voice Journal VPS Setup
# Run as root on a fresh Hetzner CX22/CX23 (Ubuntu 22.04/24.04)
# Processes overnight at 02:00 Europe/Warsaw — ready for morning debrief
# ============================================================

APP_DIR="/opt/voice-journal"
APP_USER="journal"
RECEIVER_PORT=8675

echo "=== Voice Journal VPS Setup ==="

# --- 1. System packages ---
echo "[1/7] Installing system packages..."
apt update -qq
apt install -y -qq python3 python3-pip python3-venv ufw nginx certbot python3-certbot-nginx

# --- 2. Create app user ---
echo "[2/7] Creating app user..."
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --shell /bin/bash --home-dir "$APP_DIR" "$APP_USER"
fi

# --- 3. Create directory structure ---
echo "[3/7] Setting up directories..."
mkdir -p "$APP_DIR"/{inbox,archive/audio,archive/markdown}
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# --- 4. Copy app files ---
echo "[4/7] Installing application..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/receiver.py" "$APP_DIR/"
cp "$SCRIPT_DIR/voice_journal.py" "$APP_DIR/"

if [ ! -f "$APP_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$APP_DIR/.env"
    # Generate upload token automatically
    TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i "s/UPLOAD_TOKEN=GENERATE_ME/UPLOAD_TOKEN=$TOKEN/" "$APP_DIR/.env"
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  UPLOAD TOKEN (save this for your iOS Shortcut):        ║"
    echo "║  $TOKEN  ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
    echo "  You still need to edit $APP_DIR/.env to add:"
    echo "  - GROQ_API_KEY"
    echo "  - GOOGLE_API_KEY (or ANTHROPIC_API_KEY)"
    echo "  - NOTION_TOKEN + NOTION_DATABASE_ID"
    echo ""
else
    echo "  .env already exists, skipping (not overwriting your keys)"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# --- 5. Python dependencies ---
echo "[5/7] Installing Python packages..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet groq requests python-dotenv flask gunicorn

# --- 6. Systemd units ---
echo "[6/7] Creating systemd services..."

# Set timezone first — timer OnCalendar uses system TZ
timedatectl set-timezone Europe/Warsaw
echo "  Timezone set to Europe/Warsaw"

# Receiver service (always running, accepts uploads from iOS Shortcut)
cat > /etc/systemd/system/voice-journal-receiver.service << EOF
[Unit]
Description=Voice Journal Audio Receiver
After=network.target

[Service]
Type=exec
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/gunicorn \
    --bind 127.0.0.1:$RECEIVER_PORT \
    --workers 1 \
    --timeout 30 \
    --access-logfile $APP_DIR/receiver_access.log \
    receiver:app
Restart=on-failure
RestartSec=5

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

# Processing service (oneshot, triggered by timer)
cat > /etc/systemd/system/voice-journal-process.service << EOF
[Unit]
Description=Voice Journal Overnight Processing
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python3 $APP_DIR/voice_journal.py
EOF

# Timer: 02:00 Europe/Warsaw nightly
# Persistent=true means if VPS was down at 02:00, it runs on next boot
cat > /etc/systemd/system/voice-journal-process.timer << EOF
[Unit]
Description=Voice Journal Overnight Processing — 02:00 CET/CEST

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now voice-journal-receiver.service
systemctl enable --now voice-journal-process.timer

echo "  Receiver:  running on 127.0.0.1:$RECEIVER_PORT"
echo "  Timer:     02:00 Europe/Warsaw (Persistent=true)"

# --- 7. Nginx reverse proxy ---
echo "[7/7] Configuring nginx..."

cat > /etc/nginx/sites-available/voice-journal << 'EOF'
server {
    listen 80;
    server_name _;

    # Upload endpoint — proxy to receiver
    location /upload {
        proxy_pass http://127.0.0.1:8675;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 25M;
    }

    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8675;
    }

    # Block everything else
    location / {
        return 444;
    }
}
EOF

ln -sf /etc/nginx/sites-available/voice-journal /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# --- Firewall ---
ufw allow 22/tcp   # SSH
ufw allow 80/tcp   # HTTP (→ upgrade to HTTPS with certbot)
ufw allow 443/tcp  # HTTPS
ufw --force enable

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit $APP_DIR/.env with your API keys"
echo "  2. systemctl restart voice-journal-receiver"
echo "  3. Test: curl http://YOUR_VPS_IP/health"
echo "  4. Add HTTPS: certbot --nginx -d yourdomain.com"
echo "  5. Update iOS Shortcut to POST to https://yourdomain.com/upload"
echo ""
echo "Timer verification:"
echo "  systemctl list-timers | grep voice-journal   # next run time"
echo "  systemctl start voice-journal-process         # manual test run"
echo "  cat $APP_DIR/voice_journal.log                # processing output"
echo ""
echo "Receiver logs:"
echo "  journalctl -u voice-journal-receiver -f"
echo "  cat $APP_DIR/receiver.log"
