# Use a slim Python image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy and install Python dependencies first (to use Docker cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the files
COPY . .

# Expose the port and run the app
EXPOSE 8000
CMD ["gunicorn", "app:app"]
