# Use a slim Python image
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies required for Playwright Chromium (Debian packages)
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libxshmfence1 \
    libcups2 \
    libxfixes3 \
    libpango-1.0-0 \
    libcairo2

# Copy the requirement file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project files
COPY . .

# Install Playwright Chromium browser
RUN python -m playwright install chromium

# Expose the port (Railway will usually inject this)
EXPOSE 8000

# Define the command to run the app
CMD ["gunicorn", "app:app"]
