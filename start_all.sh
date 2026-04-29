#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/venv}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/.logs}"
MPLCONFIGDIR="${MPLCONFIGDIR:-$ROOT_DIR/.cache/matplotlib}"

mkdir -p "$LOG_DIR" "$MPLCONFIGDIR"

PYTHON_BIN="${PYTHON:-$VENV_DIR/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Creating Python virtual environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
  PYTHON_BIN="$VENV_DIR/bin/python"
fi

PIP_BIN="$VENV_DIR/bin/pip"
PIDS=()

cleanup() {
  if [[ ${#PIDS[@]} -gt 0 ]]; then
    echo
    echo "Stopping services started by this script..."
    for pid in "${PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
}

trap cleanup INT TERM EXIT

ensure_python_deps() {
  if MPLCONFIGDIR="$MPLCONFIGDIR" "$PYTHON_BIN" - >/dev/null 2>&1 <<'PY'
import fastapi
import lightgbm
import numpy
import pandas
import pulp
import pydantic
import sklearn
import uvicorn
PY
  then
    echo "Python dependencies: ok"
  else
    echo "Installing Python dependencies..."
    "$PIP_BIN" install -r "$ROOT_DIR/requirements.txt" -r "$ROOT_DIR/api/requirements.txt"
  fi
}

ensure_frontend_deps() {
  if [[ -d "$FRONTEND_DIR/node_modules" ]]; then
    echo "Frontend dependencies: ok"
  else
    echo "Installing frontend dependencies..."
    (cd "$FRONTEND_DIR" && npm install)
  fi
}

port_is_open() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.25)
    sys.exit(0 if sock.connect_ex((host, port)) == 0 else 1)
PY
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local attempts="${3:-90}"

  printf "Waiting for %s" "$label"
  for _ in $(seq 1 "$attempts"); do
    if "$PYTHON_BIN" - "$url" >/dev/null 2>&1 <<'PY'
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=1.0) as response:
        sys.exit(0 if response.status < 500 else 1)
except Exception:
    sys.exit(1)
PY
    then
      printf " ok\n"
      return 0
    fi
    printf "."
    sleep 1
  done

  printf " failed\n"
  return 1
}

ensure_python_deps
ensure_frontend_deps

API_URL="http://$API_HOST:$API_PORT"
FRONTEND_URL="http://$FRONTEND_HOST:$FRONTEND_PORT"

if port_is_open "$API_HOST" "$API_PORT"; then
  echo "API already listening at $API_URL"
else
  echo "Starting API at $API_URL"
  (
    cd "$ROOT_DIR"
    MPLCONFIGDIR="$MPLCONFIGDIR" "$PYTHON_BIN" -m uvicorn api.main:app --host "$API_HOST" --port "$API_PORT"
  ) >"$LOG_DIR/api.log" 2>&1 &
  PIDS+=("$!")
fi

if port_is_open "$FRONTEND_HOST" "$FRONTEND_PORT"; then
  echo "Frontend already listening at $FRONTEND_URL"
else
  echo "Starting frontend at $FRONTEND_URL"
  if [[ -n "${NEXT_PUBLIC_API_URL:-}" ]]; then
    (
      cd "$FRONTEND_DIR"
      NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" npm run dev -- --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT"
    ) >"$LOG_DIR/frontend.log" 2>&1 &
  else
    (
      cd "$FRONTEND_DIR"
      npm run dev -- --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT"
    ) >"$LOG_DIR/frontend.log" 2>&1 &
  fi
  PIDS+=("$!")
fi

wait_for_url "API" "$API_URL/health"
wait_for_url "frontend" "$FRONTEND_URL"

echo
echo "Everything is running:"
echo "  Frontend: $FRONTEND_URL"
echo "  API:      $API_URL/health"
echo
echo "Logs:"
echo "  API:      $LOG_DIR/api.log"
echo "  Frontend: $LOG_DIR/frontend.log"
echo

if [[ ${#PIDS[@]} -eq 0 ]]; then
  echo "Both ports were already active, so this launcher has nothing to keep alive."
  trap - INT TERM EXIT
  exit 0
fi

echo "Keep this terminal open. Press Ctrl-C here to stop services started by this script."
wait
