#!/usr/bin/env bash

# OpenNotebookLM production Compose launcher.
set -u

echo "========================================"
echo "   OpenNotebookLM Docker Quick Start"
echo "========================================"

if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    if ! cp .env.example .env; then
        echo "ERROR: Could not create .env."
        exit 1
    fi
    echo ".env file created."
fi

JWT_SECRET_KEY_VALUE="$(
    sed -n 's/^[[:space:]]*JWT_SECRET_KEY[[:space:]]*=[[:space:]]*//p' .env \
        | tail -n 1
)"
JWT_SECRET_KEY_VALUE="${JWT_SECRET_KEY_VALUE#"${JWT_SECRET_KEY_VALUE%%[![:space:]]*}"}"
JWT_SECRET_KEY_VALUE="${JWT_SECRET_KEY_VALUE%"${JWT_SECRET_KEY_VALUE##*[![:space:]]}"}"

if [ -z "$JWT_SECRET_KEY_VALUE" ]; then
    echo "ERROR: JWT_SECRET_KEY is blank in .env."
    echo "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    echo "Set that value in .env, then run this launcher again."
    exit 1
fi

if ! command -v docker > /dev/null 2>&1; then
    echo "ERROR: Docker is not installed. Please install Docker first."
    exit 1
fi

if ! docker compose version > /dev/null 2>&1; then
    echo "ERROR: Docker Compose v2 is not available. Install the Docker Compose plugin."
    exit 1
fi

PROFILE_ARGS=()
case "${1:-}" in
    with-ollama)
        echo "Starting with Ollama for local LLM support..."
        PROFILE_ARGS=(--profile with-ollama)
        ;;
    with-cache)
        echo "Starting with Redis cache..."
        PROFILE_ARGS=(--profile with-cache)
        ;;
    full)
        echo "Starting with all optional services..."
        PROFILE_ARGS=(--profile with-ollama --profile with-cache)
        ;;
    "")
        ;;
    *)
        echo "ERROR: Unknown profile '$1'. Use with-ollama, with-cache, or full."
        exit 2
        ;;
esac

echo "Validating production configuration..."
docker compose "${PROFILE_ARGS[@]}" config --quiet
COMPOSE_STATUS=$?
if [ "$COMPOSE_STATUS" -ne 0 ]; then
    echo "ERROR: Compose failed to validate configuration (exit $COMPOSE_STATUS)."
    exit "$COMPOSE_STATUS"
fi

echo "Starting services..."
docker compose "${PROFILE_ARGS[@]}" up -d --build --wait --wait-timeout 180
COMPOSE_STATUS=$?
if [ "$COMPOSE_STATUS" -ne 0 ]; then
    echo "ERROR: Compose failed to start services (exit $COMPOSE_STATUS)."
    exit "$COMPOSE_STATUS"
fi

echo ""
echo "========================================"
echo "   OpenNotebookLM is starting up!"
echo "========================================"
echo ""
echo "Services:"
echo "  - Backend API: http://localhost:8000"
echo "  - API Docs: http://localhost:8000/docs"
echo "  - Frontend: http://localhost:3000"

if [[ " ${PROFILE_ARGS[*]} " == *" with-ollama "* ]]; then
    echo "  - Ollama: http://ollama:11434 inside Compose (no host port)"
fi
if [[ " ${PROFILE_ARGS[*]} " == *" with-cache "* ]]; then
    echo "  - Redis: redis:6379 inside Compose (no host port)"
fi

echo ""
echo "To stop all services, run: docker compose down"
echo "To view logs, run: docker compose logs -f"
