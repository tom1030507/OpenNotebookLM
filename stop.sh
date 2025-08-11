#!/bin/bash

# OpenNotebookLM Docker Stop Script
echo "========================================"
echo "     Stopping OpenNotebookLM Services   "
echo "========================================"

# Stop all containers
echo "Stopping all containers..."
docker-compose down

# Optional: Remove volumes (uncomment if needed)
# echo "Removing volumes..."
# docker-compose down -v

echo ""
echo "✓ All services have been stopped."
echo ""
echo "To restart services, run: ./start.sh"
echo "To remove all data and volumes, run: docker-compose down -v"
echo ""
