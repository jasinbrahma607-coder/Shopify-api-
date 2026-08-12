FROM python:3.11-slim

WORKDIR /app

# Update system and install minimal dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copy the rest of the application
COPY . .

# Railway sets PORT env, default to 8080 for local
ENV PORT=8080
EXPOSE $PORT

# Start Gunicorn (shell form expands $PORT correctly)
CMD gunicorn api:app --bind 0.0.0.0:$PORT --workers 1
