FROM mcr.microsoft.com/playwright:latest
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api.py .
CMD gunicorn --bind 0.0.0.0:8080 --workers=1 --timeout=120 api:app
