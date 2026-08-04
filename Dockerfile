# Use the official Playwright Python image
FROM mcr.microsoft.com/playwright:python-3.11

WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY api.py .

# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT:-8080}", "api:app"]
