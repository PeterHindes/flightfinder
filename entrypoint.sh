#!/bin/bash

# Export environment variables to a file so cron can access them
printenv | grep -v "no_proxy" > /etc/environment

# Start cron in the foreground
cron -f
