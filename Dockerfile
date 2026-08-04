FROM python:3.11-slim

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium (Playwright browsers)
RUN playwright install chromium

COPY api.py .

# Fixed port 8080 – no $PORT expansion issues
CMD gunicorn --bind 0.0.0.0:8080 --workers=1 api:app
