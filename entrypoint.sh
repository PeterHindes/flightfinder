#!/bin/bash

# Export environment variables to a file so cron can access them
printenv | grep -v "no_proxy" > /etc/environment

# Run a startup sequence (sanity email + immediate report)
echo "Running startup sequence..."
/app/.venv/bin/python /app/compare_flights.py --startup --csv /app/trips.csv

# Start cron in the foreground
cron -f
