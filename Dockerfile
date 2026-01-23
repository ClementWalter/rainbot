# RainBot Dockerfile
# Automated tennis court booking service for Paris Tennis
# Uses Playwright with Firefox for browser automation

FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install system dependencies for Playwright/Firefox
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2t64 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    # Firefox dependencies
    libdbus-glib-1-2 \
    libxt6 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 rainbot
WORKDIR /app

# Copy requirements and install dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# Install Playwright browsers (Firefox for stealth)
RUN playwright install firefox && \
    playwright install-deps firefox

# Copy application code
COPY src/ ./src/
COPY main.py ./

# Create data directory for SQLite and change ownership to non-root user
RUN mkdir -p /app/data && \
    chown -R rainbot:rainbot /app /ms-playwright

# Switch to non-root user
USER rainbot

# Health check - verify Python and Playwright are working
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from playwright.sync_api import sync_playwright; print('OK')"

# Run the application
CMD ["python", "main.py"]
