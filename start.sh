#!/bin/bash
echo "🚀 Installing Playwright browsers..."
python -m playwright install chromium
echo "✅ Playwright browsers installed!"
echo "🚀 Starting API server..."
gunicorn app:app