#!/bin/bash

# OpenNotebookLM Quick Start Script
echo "========================================"
echo "   OpenNotebookLM Docker Quick Start    "
echo "========================================"

# Check if .env exists, if not copy from example
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo "✓ .env file created. Please update it with your settings."
fi

# Create necessary directories
echo "Creating necessary directories..."
mkdir -p data models uploads logs
echo "✓ Directories created"

# Check Docker and Docker Compose
if ! command -v docker &> /dev/null; then
    echo "✗ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "✗ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "✓ Docker and Docker Compose are installed"

# Build and start services
echo ""
echo "Starting services..."
echo "This may take a few minutes on first run..."
echo ""

# Parse arguments
PROFILE=""
if [ "$1" == "with-ollama" ]; then
    echo "Starting with Ollama for local LLM support..."
    PROFILE="--profile with-ollama"
elif [ "$1" == "with-cache" ]; then
    echo "Starting with Redis cache..."
    PROFILE="--profile with-cache"
elif [ "$1" == "full" ]; then
    echo "Starting with all optional services..."
    PROFILE="--profile with-ollama --profile with-cache"
fi

# Start Docker Compose
docker-compose up -d $PROFILE

# Wait for services to be ready
echo ""
echo "Waiting for services to be ready..."
sleep 10

# Check health
echo ""
echo "Checking service health..."
curl -f http://localhost:8000/healthz > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Backend is running at: http://localhost:8000"
    echo "✓ API docs available at: http://localhost:8000/docs"
else
    echo "⚠ Backend is not responding yet. It may still be starting..."
fi

# Check if frontend exists
if [ -d "./frontend" ]; then
    echo "✓ Frontend should be available at: http://localhost:3000"
else
    echo "⚠ Frontend directory not found. Frontend will not be available."
fi

echo ""
echo "========================================"
echo "   OpenNotebookLM is starting up!      "
echo "========================================"
echo ""
echo "Services:"
echo "  • Backend API: http://localhost:8000"
echo "  • API Docs: http://localhost:8000/docs"
echo "  • Frontend: http://localhost:3000"

if [ "$PROFILE" != "" ]; then
    if [[ $PROFILE == *"ollama"* ]]; then
        echo "  • Ollama: http://localhost:11434"
    fi
    if [[ $PROFILE == *"cache"* ]]; then
        echo "  • Redis: localhost:6379"
    fi
fi

echo ""
echo "To stop all services, run: docker-compose down"
echo "To view logs, run: docker-compose logs -f"
echo ""
