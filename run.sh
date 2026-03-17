#!/usr/bin/env bash

set -e

echo "==================================="
echo "Codes Web Application"
echo "==================================="

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ python3 not found. Install Python 3 and retry."
    exit 1
fi

# Create virtual environment if missing
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# Install required packages
echo "📦 Installing required packages..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Create necessary directories
mkdir -p database

echo "✅ Directories created"

# Check if all template files exist
if [ ! -f "templates/base.html" ]; then
    echo "⚠️  Template files missing. Please create them first."
    exit 1
fi

# Run the application
echo "🚀 Starting application..."
python app.py