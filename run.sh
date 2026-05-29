#!/bin/bash
cd "$(dirname "$0")"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Installing dependencies..."
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Load .env if exists
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo ""
echo "  AppInsight - App Intelligence Platform"
echo "  ────────────────────────────────────────"
echo "  Dashboard: http://localhost:8000"
echo "  API Docs:  http://localhost:8000/docs"
echo ""

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
