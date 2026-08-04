FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py .

# Port 8080 is fixed – no variable expansion issues
CMD gunicorn --bind 0.0.0.0:8080 --workers=1 api:app
