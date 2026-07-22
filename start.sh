#!/usr/bin/env bash
# ─── Tuncay-Klip — Single-Command Launcher (Bash) ─────────────
# Usage:
#   ./start.sh              # Docker mode (default)
#   ./start.sh --local      # Local Python mode (no Docker)
#   ./start.sh --monitoring # Include Grafana + Prometheus
#   ./start.sh --generate-key  # Generate a fresh ADMIN_API_KEY and exit

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="docker"
MONITORING=false
GENERATE_KEY=false

# ── Parse args ───────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --local) MODE="local"; shift ;;
        --monitoring) MONITORING=true; shift ;;
        --generate-key) GENERATE_KEY=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║     Tuncay-Klip — Intelligence System    ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Helpers ──────────────────────────────────────────────────────
ensure_dotenv() {
    if [[ ! -f "$ROOT/.env" ]]; then
        if [[ -f "$ROOT/.env.example" ]]; then
            echo "  [setup] .env not found — copying from .env.example"
            cp "$ROOT/.env.example" "$ROOT/.env"
        else
            echo "  [error] Neither .env nor .env.example found"
            exit 1
        fi
    fi
}

generate_secret() {
    if command -v openssl &>/dev/null; then
        openssl rand -base64 "$1" | tr -d '\n' | head -c "$1"
    elif [[ -f /dev/urandom ]]; then
        head -c "$1" /dev/urandom | base64 | tr -d '\n/' | head -c "$1"
    else
        python3 -c "import secrets; print(secrets.token_urlsafe($1)[:${1}])"
    fi
}

update_env_var() {
    local key="$1" value="$2"
    if grep -q "^${key}=" "$ROOT/.env" 2>/dev/null; then
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "$ROOT/.env"
        rm -f "$ROOT/.env.bak"
    else
        echo "${key}=${value}" >> "$ROOT/.env"
    fi
}

get_env_var() {
    grep "^${1}=" "$ROOT/.env" 2>/dev/null | head -1 | cut -d'=' -f2-
}

# ── Secret Generation ────────────────────────────────────────────
ensure_dotenv

secret_key=$(get_env_var "SECRET_KEY")
if [[ -z "$secret_key" || "$secret_key" == *"change-me"* ]]; then
    new_secret=$(generate_secret 64)
    update_env_var "SECRET_KEY" "$new_secret"
    echo "  [setup] Generated new SECRET_KEY"
fi

admin_key=$(get_env_var "ADMIN_API_KEY")
if [[ -z "$admin_key" || "$admin_key" == *"change-me"* ]]; then
    raw_key="ip_$(generate_secret 43)"
    update_env_var "ADMIN_API_KEY" "$raw_key"
    echo "  [setup] Generated ADMIN_API_KEY: $raw_key"
    echo "           Copy this key to Dashboard 'API Key' input"
fi

admin_key=$(get_env_var "ADMIN_API_KEY")

if [[ "$GENERATE_KEY" == true ]]; then
    echo ""
    echo "  ADMIN_API_KEY = $admin_key"
    echo ""
    exit 0
fi

# ── Local Python Mode ───────────────────────────────────────────
if [[ "$MODE" == "local" ]]; then
    echo "  [mode] Local Python (no Docker)"

    if [[ ! -d "$ROOT/.venv" ]]; then
        echo "  [setup] Creating virtual environment..."
        python3 -m venv "$ROOT/.venv"
    fi

    source "$ROOT/.venv/bin/activate"
    pip install -q -r "$ROOT/requirements-ml.txt"

    echo "  [run] Starting uvicorn on http://localhost:8000"
    echo "  [auth] Dashboard API Key: $admin_key"
    echo ""
    exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload
fi

# ── Docker Mode ──────────────────────────────────────────────────
echo "  [mode] Docker Compose"

if ! command -v docker &>/dev/null; then
    echo "  [error] Docker not found. Install Docker first."
    echo "  [hint]  Or use: ./start.sh --local"
    exit 1
fi

if ! docker info &>/dev/null 2>&1; then
    echo "  [error] Docker daemon not running. Start Docker first."
    echo "  [hint]  Or use: ./start.sh --local"
    exit 1
fi

# Check POSTGRES_PASSWORD
db_pass=$(get_env_var "POSTGRES_PASSWORD")
if [[ -z "$db_pass" || "$db_pass" == *"change-me"* ]]; then
    new_db_pass=$(generate_secret 32)
    update_env_var "POSTGRES_PASSWORD" "$new_db_pass"
    echo "  [setup] Generated POSTGRES_PASSWORD"
fi

# Check GRAFANA_ADMIN_PASSWORD (only needed if monitoring profile used)
if [[ "$MONITORING" == true ]]; then
    grafana_pass=$(get_env_var "GRAFANA_ADMIN_PASSWORD")
    if [[ -z "$grafana_pass" || "$grafana_pass" == *"change-me"* ]]; then
        new_grafana_pass=$(generate_secret 24)
        update_env_var "GRAFANA_ADMIN_PASSWORD" "$new_grafana_pass"
        echo "  [setup] Generated GRAFANA_ADMIN_PASSWORD"
    fi
fi

# Ensure data directories
mkdir -p "$ROOT/data" "$ROOT/logs" "$ROOT/clips" "$ROOT/models_store"

# Build and launch
echo "  [build] Building Docker image..."
docker compose build

profiles=()
if [[ "$MONITORING" == true ]]; then
    profiles+=("--profile" "monitoring")
fi

echo "  [run] Starting services..."
echo "  [auth] Dashboard API Key: $admin_key"
echo "  [url]  http://localhost:8000"
echo ""

docker compose up "${profiles[@]}"
