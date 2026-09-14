#!/usr/bin/env bash

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUNTIME_DIR="$ROOT_DIR/.runtime"
OWNED_DIR="$RUNTIME_DIR/started_by_stack"
PID_DIR="$RUNTIME_DIR/pids"

echo ""
echo "============================================================"
echo " Deteniendo Local AI Stack"
echo "============================================================"
echo ""

if [ ! -d "$OWNED_DIR" ]; then
    echo "No hay servicios registrados como iniciados por el stack."
    exit 0
fi

python3 - <<'PY' > /tmp/local_ai_stop_services.tsv
import yaml

with open("config/services.yaml", encoding="utf-8") as f:
    services = yaml.safe_load(f)["services"]

by_id = {s["id"]: s for s in services}
ordered = []
temporary = set()
permanent = set()

def visit(service_id):
    if service_id in permanent:
        return

    if service_id in temporary:
        raise RuntimeError(
            f"Dependencia circular detectada: {service_id}"
        )

    temporary.add(service_id)
    service = by_id[service_id]

    for dependency in service.get("depends_on", []):
        visit(dependency)

    temporary.remove(service_id)
    permanent.add(service_id)
    ordered.append(service)

for service in services:
    visit(service["id"])

for s in reversed(ordered):
    print(
        "\t".join([
            s["id"],
            str(s.get("stop_command") or "").replace("\t", " "),
        ])
    )
PY

while IFS=$'\t' read -r id command; do
    if [ ! -f "$OWNED_DIR/$id" ]; then
        continue
    fi

    printf "%-20s " "$id"

    stopped=0

    if [ -f "$PID_DIR/$id" ]; then
        pid="$(cat "$PID_DIR/$id")"

        if kill -0 "$pid" >/dev/null 2>&1; then
            kill "$pid" >/dev/null 2>&1 || true

            attempts=0
            while kill -0 "$pid" >/dev/null 2>&1 && [ "$attempts" -lt 20 ]; do
                sleep 0.25
                attempts=$((attempts + 1))
            done

            if kill -0 "$pid" >/dev/null 2>&1; then
                kill -9 "$pid" >/dev/null 2>&1 || true
                sleep 0.2
            fi
        fi

        if ! kill -0 "$pid" >/dev/null 2>&1; then
            stopped=1
        fi
    fi

    if [ "$stopped" -eq 0 ] && [ -n "$command" ]; then
        if bash -c "cd '$ROOT_DIR' && $command" >/dev/null 2>&1; then
            stopped=1
        fi
    fi

    if [ "$stopped" -eq 1 ]; then
        rm -f "$OWNED_DIR/$id" "$PID_DIR/$id"
        echo "STOPPED"
    else
        echo "ERROR"
    fi
done < /tmp/local_ai_stop_services.tsv

rm -f /tmp/local_ai_stop_services.tsv

echo ""
echo "Servicios iniciados por este stack detenidos."
echo "Los servicios que ya estaban activos antes no se han tocado."
echo ""
