FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY mock_api.py .
CMD gunicorn --bind 0.0.0.0:8080 mock_api:app
