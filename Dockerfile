# Multi-stage build: SPA frontend + Python backend with Playwright
# Stage 1 builds the Vite SPA, Stage 2 runs the FastAPI app with browser automation

# -- Stage 1: Build web frontend --
FROM oven/bun:1 AS web-builder
WORKDIR /app/web
COPY web/package.json web/bun.lock ./
RUN bun install --frozen-lockfile
COPY web/ ./
RUN bun run build

# -- Stage 2: Python runtime with Playwright --
FROM python:3.12-slim AS runtime

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install Python dependencies first (cache layer)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Install Playwright Chromium and its system deps via the venv directly
# (avoids uv run trying to build the project before src/ is copied)
RUN .venv/bin/playwright install --with-deps chromium

# Copy application code and install the project
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# Copy built SPA from stage 1
COPY --from=web-builder /app/web/dist ./web/dist

# Create data directory for SQLite
RUN mkdir -p /app/data

EXPOSE 8000

# Run the webapp; scheduler starts as a daemon thread inside the process
CMD ["uv", "run", "paris-tennis-webapp", "--host", "0.0.0.0", "--port", "8000"]
