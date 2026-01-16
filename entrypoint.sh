#!/bin/bash

# Export environment variables to a file so cron can access them
printenv | grep -v "no_proxy" > /etc/environment

# Run a sanity check email on startup
echo "Running startup sanity check..."
/app/.venv/bin/python /app/compare_flights.py --sanity

# Start cron in the foreground
cron -f
