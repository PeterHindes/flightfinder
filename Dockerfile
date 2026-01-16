FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Copy dependency files
COPY pyproject.toml .
COPY uv.lock .

# Install dependencies
RUN uv sync --frozen --extra local

# Install Playwright browsers
RUN uv run playwright install --with-deps chromium

# Copy the rest of the application
COPY . .

# Default command
CMD ["uv", "run", "python", "compare_flights.py", "--csv", "trips.csv", "--email"]
