FROM mcr.microsoft.com/playwright:latest

# Install Python pip (the image has Python but not pip)
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the app
COPY api.py .

# Run with gunicorn (use python3 explicitly)
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT:-8080}", "--workers=1", "--timeout=120", "api:app"]
