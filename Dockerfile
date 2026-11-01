# Use official Microsoft Playwright image
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    HEADLESS=True \
    PORT=8080

# Set working directory
WORKDIR /app

# Copy requirement files first for layer caching
COPY requirements.txt .

# Install Python packages and install Playwright chromium binary explicitly
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium

# Copy application source code
COPY . .

# Expose port
EXPOSE 8080

# Command to run bot
CMD ["python", "main.py"]
