FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY wrapper_api.py .
CMD gunicorn --bind 0.0.0.0:8080 wrapper_api:app
