#!/bin/bash
# 🎮 Flipkart PlayStation Stock Monitor Bot - AWS EC2 Setup Script 🎮
# Usage: bash setup_aws.sh

set -e

echo "📦 Updating system packages..."
sudo apt-get update -y

echo "🐍 Installing Python 3 & venv dependencies..."
sudo apt-get install -y python3 python3-venv python3-pip git curl

echo "📁 Setting up virtual environment..."
cd ~/flipkart-bot
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

echo "📦 Installing Python libraries..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🌐 Installing Playwright Chromium and system dependencies..."
python3 -m playwright install chromium
sudo python3 -m playwright install-deps chromium

echo "⚙️ Configuring systemd background service..."
sudo cp flipkart-bot.service /etc/systemd/system/flipkart-bot.service
sudo systemctl daemon-reload
sudo systemctl enable flipkart-bot
sudo systemctl restart flipkart-bot

echo "✅ Setup complete! Flipkart Monitor Bot is now running 24/7."
echo "📜 View live logs with:"
echo "   sudo journalctl -u flipkart-bot -f"
