FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (optional but helpful)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE $PORT

CMD ["python", "api.py"]
