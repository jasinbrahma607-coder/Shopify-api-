FROM mcr.microsoft.com/playwright:latest

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY api.py .

# ✅ Shell form: $PORT will be expanded correctly
CMD gunicorn --bind 0.0.0.0:${PORT:-8080} --workers=1 --timeout=120 api:app
