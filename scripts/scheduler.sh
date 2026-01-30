#!/bin/bash
# Scheduler script for running periodic Django management commands
# This script runs in a loop and executes scheduled tasks

set -e

echo "Starting JAR scheduler..."
echo "Current time: $(date)"

# Wait for the database to be ready
echo "Waiting for database..."
sleep 10

# Run migrations if needed (only on first start)
if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "Running migrations..."
    python manage.py migrate --noinput
fi

echo "Scheduler started successfully"

# Main loop - runs every minute and checks what needs to be done
while true; do
    current_minute=$(date +%M)
    current_hour=$(date +%H)

    # Run match reminders at the top of every hour (minute 0)
    if [ "$current_minute" = "00" ]; then
        echo "[$(date)] Running send_match_reminders..."
        python manage.py send_match_reminders || echo "Match reminders command failed"
    fi

    # Run unaccepted match reminders at minute 30 of every hour
    # This is for the "pending" matches that haven't been accepted yet
    if [ "$current_minute" = "30" ]; then
        echo "[$(date)] Running send_unaccepted_reminders..."
        python manage.py send_unaccepted_reminders || echo "Unaccepted reminders command failed (command may not exist)"
    fi

    # Add more scheduled tasks here as needed
    # Example: Daily cleanup at 3:00 AM
    # if [ "$current_hour" = "03" ] && [ "$current_minute" = "00" ]; then
    #     python manage.py clearsessions
    # fi

    # Sleep for 60 seconds before next check
    sleep 60
done
