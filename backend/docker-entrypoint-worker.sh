# Worker entry point script
#!/bin/bash

# Wait for Redis to be ready
echo "Waiting for Redis..."
until python -c "import redis; r = redis.from_url('$REDIS_URL'); r.ping()" 2>/dev/null; do
    sleep 1
done

echo "Redis is ready!"

# Run the worker
exec python -m app.workers.main