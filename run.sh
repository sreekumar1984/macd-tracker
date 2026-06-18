#!/bin/bash

# Navigate to the project directory
cd /Users/sree/macd_momentum_tracker

echo "=========================================================="
echo "📦 Setting up isolated environment for MACD Momentum Tracker..."
echo "=========================================================="

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment 'venv'..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies (requirements.txt)..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "=========================================================="
echo "🚀 Starting MACD Momentum Tracker Daemon..."
echo "=========================================================="
# Run the tracker
python -u tracker.py
