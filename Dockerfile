FROM python:3.13-slim

WORKDIR /app

# Install system dependencies required by Playwright
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy the app
COPY api.py .

# Run with gunicorn (or directly with python)
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT:-8080}", "api:app"]
