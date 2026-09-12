#!/usr/bin/env bash

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUNTIME_DIR="$ROOT_DIR/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"
STATUS_DIR="$RUNTIME_DIR/status"
OWNED_DIR="$RUNTIME_DIR/started_by_stack"
PID_DIR="$RUNTIME_DIR/pids"

mkdir -p "$LOG_DIR" "$STATUS_DIR" "$OWNED_DIR" "$PID_DIR"
rm -f "$STATUS_DIR"/* 2>/dev/null || true

echo ""
echo "============================================================"
echo " Local AI Stack"
echo "============================================================"
echo ""

is_ready() {
    local id="$1"
    local host="$2"
    local port="$3"
    local health="$4"

    case "$id" in
        database)
            command -v pg_isready >/dev/null 2>&1 &&
            pg_isready -h "${host:-127.0.0.1}" -p "${port:-5432}" \
                >/dev/null 2>&1
            return
            ;;
        queue)
            command -v redis-cli >/dev/null 2>&1 &&
            redis-cli -h "${host:-127.0.0.1}" \
                -p "${port:-6379}" ping 2>/dev/null |
                grep -q PONG
            return
            ;;
        worker_fetch)
            pgrep -f "rq worker fetch" >/dev/null 2>&1
            return
            ;;
        worker_process)
            pgrep -f "rq worker.*process" >/dev/null 2>&1
            return
            ;;
        worker_notify)
            pgrep -f "rq worker notify" >/dev/null 2>&1
            return
            ;;
        worker_scientific)
            pgrep -f "rq worker.*protocol_designer" >/dev/null 2>&1
            return
            ;;
    esac

    if [ -n "$port" ] && [ -n "$health" ]; then
        curl -fsS \
            --max-time 2 \
            "http://${host}:${port}${health}" \
            >/dev/null 2>&1
        return
    fi

    if [ -n "$port" ]; then
        nc -z "$host" "$port" >/dev/null 2>&1
        return
    fi

    return 1
}

wait_ready() {
    local id="$1"
    local host="$2"
    local port="$3"
    local health="$4"
    local attempts=0
    local max_attempts=40

    while [ "$attempts" -lt "$max_attempts" ]; do
        if is_ready "$id" "$host" "$port" "$health"; then
            return 0
        fi

        attempts=$((attempts + 1))
        sleep 1
    done

    return 1
}

dependency_failed() {
    local deps="$1"

    [ -z "$deps" ] && return 1

    OLD_IFS="$IFS"
    IFS=','
    for dep in $deps; do
        IFS="$OLD_IFS"

        [ -z "$dep" ] && continue

        if [ ! -f "$STATUS_DIR/$dep" ]; then
            return 0
        fi

        state="$(cat "$STATUS_DIR/$dep")"

        if [ "$state" != "OK" ]; then
            return 0
        fi

        IFS=','
    done
    IFS="$OLD_IFS"

    return 1
}

start_service() {
    local id="$1"
    local name="$2"
    local host="$3"
    local port="$4"
    local health="$5"
    local command="$6"
    local deps="$7"

    printf "%-20s " "$id"

    if dependency_failed "$deps"; then
        echo "SKIPPED (dependencia no disponible)"
        echo "SKIPPED" > "$STATUS_DIR/$id"
        return
    fi

    if is_ready "$id" "$host" "$port" "$health"; then
        echo "OK (ya estaba activo)"
        echo "OK" > "$STATUS_DIR/$id"
        return
    fi

    logfile="$LOG_DIR/${id}.log"

    echo "STARTING"

    nohup env PATH="$PATH" VIRTUAL_ENV="${VIRTUAL_ENV:-}" \
        bash -c "cd '$ROOT_DIR' && $command" \
        >> "$logfile" 2>&1 &

    pid=$!
    echo "$pid" > "$PID_DIR/$id"
    touch "$OWNED_DIR/$id"

    if wait_ready "$id" "$host" "$port" "$health"; then
        printf "%-20s %s\n" "$id" "OK"
        echo "OK" > "$STATUS_DIR/$id"
    else
        printf "%-20s %s\n" "$id" "ERROR"
        echo "ERROR" > "$STATUS_DIR/$id"

        echo "  Log: $logfile"
        tail -5 "$logfile" 2>/dev/null | sed 's/^/    /'
    fi
}

while IFS=$'\x1f' read -r id name host port health command deps; do
    start_service \
        "$id" \
        "$name" \
        "$host" \
        "$port" \
        "$health" \
        "$command" \
        "$deps"
done < <(
python3 - <<'PY'
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
            f"Dependencia circular detectada en {service_id}"
        )

    temporary.add(service_id)

    service = by_id[service_id]

    for dependency in service.get("depends_on", []):
        if dependency not in by_id:
            raise RuntimeError(
                f"Dependencia desconocida: "
                f"{service_id} -> {dependency}"
            )
        visit(dependency)

    temporary.remove(service_id)
    permanent.add(service_id)
    ordered.append(service)

for service in services:
    visit(service["id"])

for s in ordered:
    fields = [
        s.get("id", ""),
        s.get("name", ""),
        str(s.get("host") or ""),
        str(s.get("port") or ""),
        str(s.get("health_endpoint") or ""),
        str(s.get("start_command") or ""),
        ",".join(s.get("depends_on") or []),
    ]

    print("\x1f".join(
        value.replace("\x1f", " ").replace("\n", " ")
        for value in fields
    ))
PY
)

echo ""
echo "============================================================"
echo " Estado final"
echo "============================================================"

errors=0

for status_file in "$STATUS_DIR"/*; do
    [ -e "$status_file" ] || continue

    id="$(basename "$status_file")"
    state="$(cat "$status_file")"

    printf " %-20s %s\n" "$id" "$state"

    if [ "$state" = "ERROR" ]; then
        errors=$((errors + 1))
    fi
done

echo ""

if [ "$errors" -eq 0 ]; then
    echo "Stack arrancado."
    echo "Dashboard: http://127.0.0.1:8765"
else
    echo "Stack arrancado con $errors servicio(s) con error."
    echo "Logs: $LOG_DIR"
fi

echo ""
