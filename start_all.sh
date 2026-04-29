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
USE_DOPPLER="${USE_DOPPLER:-auto}"
DOPPLER_RUN_ARGS="${DOPPLER_RUN_ARGS:-}"
REQUIRE_GROQ_KEY="${REQUIRE_GROQ_KEY:-1}"
REUSE_EXISTING_SERVICES="${REUSE_EXISTING_SERVICES:-0}"

is_truthy() {
  case "${1:-}" in
    1|true|True|TRUE|yes|Yes|YES|on|On|ON|required|Required|REQUIRED) return 0 ;;
    *) return 1 ;;
  esac
}

has_groq_key() {
  [[ -n "${GROQ_API_KEY:-}" || -n "${GROQ_API_TOKEN:-}" ]]
}

already_running_with_doppler() {
  [[ -n "${DOPPLER_PROJECT:-}" && -n "${DOPPLER_CONFIG:-}" ]]
}

should_skip_doppler() {
  case "$USE_DOPPLER" in
    0|false|False|FALSE|off|Off|OFF|no|No|NO) return 0 ;;
    *) return 1 ;;
  esac
}

should_require_doppler() {
  is_truthy "$USE_DOPPLER"
}

ensure_doppler_context() {
  if should_skip_doppler; then
    echo "Doppler: disabled by USE_DOPPLER=$USE_DOPPLER"
    return
  fi

  if already_running_with_doppler; then
    echo "Doppler: active (${DOPPLER_PROJECT}/${DOPPLER_CONFIG})"
    return
  fi

  if [[ -n "${VERCEL:-}" ]] && has_groq_key; then
    echo "Doppler: using Vercel-injected environment"
    return
  fi

  if [[ -n "${ETW_DOPPLER_WRAPPED:-}" ]]; then
    echo "Doppler: wrapper already attempted; continuing with current environment"
    return
  fi

  if command -v doppler >/dev/null 2>&1; then
    echo "Doppler: launching services with injected secrets"
    if [[ -n "$DOPPLER_RUN_ARGS" ]]; then
      # DOPPLER_RUN_ARGS is intended for simple flags, e.g.
      # "--project bess-optimizer --config dev".
      exec env ETW_DOPPLER_WRAPPED=1 doppler run $DOPPLER_RUN_ARGS -- "$0" "$@"
    fi
    exec env ETW_DOPPLER_WRAPPED=1 doppler run -- "$0" "$@"
  fi

  if should_require_doppler; then
    echo "Doppler CLI is required but was not found. Install Doppler or set USE_DOPPLER=0 for local env fallback." >&2
    exit 1
  fi

  echo "Doppler: CLI not found; continuing with current environment"
}

ensure_doppler_context "$@"

if is_truthy "$REQUIRE_GROQ_KEY" && ! has_groq_key; then
  echo "Missing GROQ_API_KEY. Add it to Doppler, then run ./start_all.sh again." >&2
  echo "For local fallback without the chatbot, run REQUIRE_GROQ_KEY=0 USE_DOPPLER=0 ./start_all.sh" >&2
  exit 1
fi

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
  trap - INT TERM EXIT
  if [[ ${#PIDS[@]} -gt 0 ]]; then
    echo
    echo "Stopping services started by this script..."
    for pid in "${PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    wait "${PIDS[@]}" 2>/dev/null || true
    PIDS=()
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
FRONTEND_API_URL="${NEXT_PUBLIC_API_URL:-}"

if port_is_open "$API_HOST" "$API_PORT"; then
  if is_truthy "$REUSE_EXISTING_SERVICES"; then
    echo "API already listening at $API_URL"
  else
    echo "API port is already in use at $API_URL." >&2
    echo "Stop the old process, choose another API_PORT, or set REUSE_EXISTING_SERVICES=1 if you know it is already Doppler-backed." >&2
    exit 1
  fi
else
  echo "Starting API at $API_URL"
  (
    cd "$ROOT_DIR"
    MPLCONFIGDIR="$MPLCONFIGDIR" "$PYTHON_BIN" -m uvicorn api.main:app --host "$API_HOST" --port "$API_PORT"
  ) >"$LOG_DIR/api.log" 2>&1 &
  PIDS+=("$!")
fi

if port_is_open "$FRONTEND_HOST" "$FRONTEND_PORT"; then
  if is_truthy "$REUSE_EXISTING_SERVICES"; then
    echo "Frontend already listening at $FRONTEND_URL"
  else
    echo "Frontend port is already in use at $FRONTEND_URL." >&2
    echo "Stop the old Next.js process, choose another FRONTEND_PORT, or set REUSE_EXISTING_SERVICES=1 if you know it is already Doppler-backed." >&2
    exit 1
  fi
else
  echo "Starting frontend at $FRONTEND_URL"
  (
    cd "$FRONTEND_DIR"
    INTERNAL_API_URL="$API_URL" NEXT_PUBLIC_API_URL="$FRONTEND_API_URL" npm run dev -- --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT"
  ) >"$LOG_DIR/frontend.log" 2>&1 &
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
