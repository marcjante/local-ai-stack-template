#!/usr/bin/env bash
# stop_stack.sh
# Para todos los servicios definidos en config/services.yaml, en orden inverso
# a como se definen (para respetar dependencias al apagar).

set -e
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 - <<'PY'
import yaml, subprocess
with open("config/services.yaml") as f:
    data = yaml.safe_load(f)
for s in reversed(data["services"]):
    print(f"Parando {s['id']} ({s['name']})...")
    subprocess.run(s["stop_command"], shell=True)
PY

echo "Stack parado."
