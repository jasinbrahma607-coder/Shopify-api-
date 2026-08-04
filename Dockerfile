FROM mcr.microsoft.com/playwright:latest

# Install pip (the base image has Python but not pip)
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api.py .

CMD gunicorn --bind 0.0.0.0:8080 --workers=1 --timeout=120 api:app
