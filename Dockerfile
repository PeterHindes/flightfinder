FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# Install cron
RUN apt-get update && apt-get install -y \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files and source for metadata
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY fast_flights ./fast_flights

# Install dependencies
RUN uv sync --frozen --extra local

# Install Playwright browsers
RUN uv run playwright install chromium

# Copy the rest of the application
COPY . .

# Set up cron job (runs at noon every day)
# We use 'BASH_ENV=/etc/environment' to ensure cron has access to Docker env vars
RUN echo "0 12 * * * . /etc/environment; /app/.venv/bin/python /app/compare_flights.py --csv /app/trips.csv --email >> /var/log/cron.log 2>&1" > /etc/cron.d/flight-cron
RUN chmod 0644 /etc/cron.d/flight-cron
RUN crontab /etc/cron.d/flight-cron
RUN touch /var/log/cron.log

# Use entrypoint script to start cron
ENTRYPOINT ["/app/entrypoint.sh"]
