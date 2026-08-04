# Use Python 3.11 with all common libraries
FROM python:3.11-slim

# Install Playwright's system dependencies
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium browser (Playwright will download to default location)
RUN playwright install chromium

# Copy the app
COPY api.py .

# Expose port (Railway sets PORT env)
EXPOSE 8080

# Run directly with Python (not gunicorn) for simplicity and to see errors
CMD ["python", "api.py"]
