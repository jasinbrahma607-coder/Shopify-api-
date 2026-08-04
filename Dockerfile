# Use the official Playwright image (Ubuntu-based, includes all browsers)
FROM mcr.microsoft.com/playwright:latest

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY api.py .

# Start the server
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT:-8080}", "api:app"]
