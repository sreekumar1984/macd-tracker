#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "=========================================================="
echo "🚀 MACD MOMENTUM TRACKER - GCP AUTO DEPLOYMENT SCRIPT"
echo "=========================================================="

# Check if run as root
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run this script as root (use: sudo bash deploy_gcp.sh)"
  exit 1
fi

# 1. Update package lists
echo "🔄 Updating package lists..."
apt-get update -y

# 2. Install dependencies
echo "📦 Installing Python, Git, and Nginx..."
apt-get install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx

# 3. Setup Project Directory
PROJECT_DIR="/opt/macd-tracker"
if [ -d "$PROJECT_DIR" ]; then
  echo "📂 Project directory already exists at $PROJECT_DIR. Backing it up..."
  mv "$PROJECT_DIR" "${PROJECT_DIR}_backup_$(date +%s)"
fi

echo "📥 Cloning repository..."
git clone https://github.com/sreekumar1984/macd-tracker.git "$PROJECT_DIR"
cd "$PROJECT_DIR"

# 4. Setup Python Virtual Environment
echo "🐍 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "⚙️ Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. Create Systemd Service for the Tracker Daemon
echo "⚙️ Creating Systemd service for daemon..."
cat <<EOF > /etc/systemd/system/macd-tracker.service
[Unit]
Description=MACD Momentum Tracker Daemon
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python -u tracker.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and start service
echo "🔄 Starting MACD Tracker service..."
systemctl daemon-reload
systemctl enable macd-tracker.service
systemctl restart macd-tracker.service

# 6. Configure Nginx Reverse Proxy
echo "🌐 Configuring Nginx reverse proxy..."
cat <<EOF > /etc/nginx/sites-available/macd-tracker
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Enable the config and disable default Nginx page
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/macd-tracker /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx

echo "=========================================================="
echo "✅ DEPLOYMENT SUCCESSFULLY COMPLETED!"
echo "=========================================================="
echo "👉 The app is now running in the background."
echo "👉 You can access the dashboard at your VM's public IP address."
echo ""
echo "🔐 TO SET UP HTTPS (SSL):"
echo "1. Point a custom domain (e.g. tracker.yourdomain.com) to your VM's Public IP."
echo "2. Run this command inside the VM terminal to enable HTTPS automatically:"
echo "   sudo certbot --nginx -d tracker.yourdomain.com"
echo "=========================================================="
