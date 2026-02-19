#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ACTION="${1:-status}"
PROFILE="${2:-dev}"

if [[ "$PROFILE" != "dev" && "$PROFILE" != "prod" ]]; then
  echo "[ERROR] profile must be 'dev' or 'prod'"
  echo "usage: ./service.sh {on|off|restart|rebuild|status|logs} [dev|prod]"
  exit 1
fi

if [[ "$PROFILE" == "prod" ]]; then
  COMPOSE_FILE="docker-compose.prod.yml"
  ENV_FILE=".env.production"
else
  COMPOSE_FILE="docker-compose.yml"
  ENV_FILE=".env"
fi

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

read_port_from_env() {
  local port
  if [[ -f "$ENV_FILE" ]]; then
    port="$(grep -E '^APP_PORT=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)"
  else
    port=""
  fi
  if [[ -z "${port:-}" ]]; then
    port="18080"
  fi
  echo "$port"
}

wait_for_health() {
  local port="$1"
  local max_wait="${2:-30}"
  local elapsed=0
  while (( elapsed < max_wait )); do
    if curl -fsS "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

ensure_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    return
  fi
  if [[ "$PROFILE" == "dev" && -f ".env.example" ]]; then
    cp .env.example .env
    echo "[INFO] .env was missing. copied from .env.example"
    return
  fi
  echo "[ERROR] $ENV_FILE file not found."
  exit 1
}

ensure_env_file

show_usage() {
  echo "usage: ./service.sh {on|off|restart|rebuild|status|logs} [dev|prod]"
}

run_up() {
  local mode="${1:-normal}"
  if [[ "$mode" == "build" ]]; then
    compose up -d --build
    return
  fi

  # In prod, default to no-build to avoid slow deploy loops on small VPS instances.
  if [[ "$PROFILE" == "prod" ]]; then
    compose up -d
  else
    compose up -d --build
  fi
}

case "$ACTION" in
  on)
    echo "[INFO] Starting services (profile=$PROFILE, compose=$COMPOSE_FILE)"
    run_up normal
    compose ps
    if [[ "$PROFILE" == "dev" ]]; then
      APP_PORT="$(read_port_from_env)"
      if wait_for_health "$APP_PORT" 30; then
        echo "[OK] Health check passed: http://127.0.0.1:${APP_PORT}/health"
      else
        echo "[WARN] Health check failed. See logs with: ./service.sh logs $PROFILE"
      fi
    fi
    ;;
  off)
    echo "[INFO] Stopping services (profile=$PROFILE, compose=$COMPOSE_FILE)"
    compose down
    ;;
  restart)
    echo "[INFO] Restarting services (profile=$PROFILE, compose=$COMPOSE_FILE)"
    compose down
    run_up normal
    compose ps
    ;;
  rebuild)
    echo "[INFO] Rebuilding images and starting services (profile=$PROFILE, compose=$COMPOSE_FILE)"
    compose down
    run_up build
    compose ps
    ;;
  status)
    compose ps
    ;;
  logs)
    if [[ "$PROFILE" == "prod" ]]; then
      compose logs -f app worker caddy
    else
      compose logs -f app worker
    fi
    ;;
  *)
    echo "[ERROR] unknown action: $ACTION"
    show_usage
    exit 1
    ;;
esac
