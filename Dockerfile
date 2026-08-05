FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Remove any leftover file from previous builds (fixes the error)
RUN rm -f /app/wrapper_api.py

# Copy the correct file with explicit destination
COPY api.py /app/api.py

CMD gunicorn --bind 0.0.0.0:8080 api:app
