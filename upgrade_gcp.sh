#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "=========================================================="
echo "🔄 MACD MOMENTUM TRACKER - GCP UPGRADE SCRIPT"
echo "=========================================================="

# Check if run as root
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run this script as root (use: sudo bash upgrade_gcp.sh)"
  exit 1
fi

PROJECT_DIR="/opt/macd-tracker"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "❌ Project directory not found at $PROJECT_DIR."
  exit 1
fi

cd "$PROJECT_DIR"

echo "🛑 Stopping macd-tracker service..."
systemctl stop macd-tracker.service || true

echo "📥 Pulling latest updates from GitHub..."
# Configure git safe directory just in case
git config --global --add safe.directory "$PROJECT_DIR" || true
git fetch origin
git reset --hard origin/main

echo "🐍 Upgrading virtual environment packages..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "🔄 Restarting macd-tracker service..."
systemctl daemon-reload
systemctl restart macd-tracker.service

echo "=========================================================="
echo "✅ UPGRADE SUCCESSFULLY COMPLETED!"
echo "=========================================================="
echo "👉 The updated app is now running with 45m MACD and AI Optimizer."
echo "👉 Check status with: sudo systemctl status macd-tracker.service"
echo "=========================================================="
