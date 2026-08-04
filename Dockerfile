# Use Python 3.11 (has wheels for greenlet, no compilation issues)
FROM python:3.11-slim

# Install system dependencies required by Playwright
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for Playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now install Playwright browsers (will download to /ms-playwright)
RUN playwright install chromium

# Copy the application
COPY api.py .

# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT:-8080}", "api:app"]
