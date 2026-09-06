#!/usr/bin/env bash
# start_stack.sh
# Arranca todos los servicios definidos en config/services.yaml, respetando
# el orden de dependencias (depends_on). Uso genérico: no toca nada
# específico de ningún proyecto.

set -e
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Arrancando stack local..."
echo "Servicios definidos en config/services.yaml:"
python3 - <<'PY'
import yaml
with open("config/services.yaml") as f:
    data = yaml.safe_load(f)
for s in data["services"]:
    port_txt = f"puerto {s['port']}" if s.get("port") else "sin puerto propio"
    print(f" - {s['id']}: {s['name']} ({port_txt})")
PY

echo ""
echo "Para arrancar cada servicio, usa el panel de control:"
echo "  python3 dashboard/dashboard_service.py"
echo "y abre http://localhost:8090"
echo ""
echo "O arráncalos manualmente uno a uno según el 'start_command' de cada"
echo "entrada en config/services.yaml, respetando el orden de 'depends_on'."
