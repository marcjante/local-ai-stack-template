#!/usr/bin/env bash
set -euo pipefail

ROOT="$(pwd)"

if [ ! -d ".git" ]; then
  echo "ERROR: ejecuta este instalador desde la raíz de local-ai-stack-template (donde está .git)."
  exit 1
fi

echo "Configurando Codex en: $ROOT"

mkdir -p .codex/logs

# AGENTS.md: no pisar uno existente.
if [ -f "AGENTS.md" ]; then
  stamp="$(date +%Y%m%d-%H%M%S)"
  cp AGENTS.md "AGENTS.md.backup-$stamp"
  echo "Ya existía AGENTS.md. Se ha creado copia: AGENTS.md.backup-$stamp"
  if ! grep -q "Local AI Studio" AGENTS.md; then
    echo
    echo "ATENCIÓN: conserva tu AGENTS.md actual. Revisa AGENTS.md.codex-template y fusiona"
    echo "sus reglas manualmente si quieres. No lo he sobrescrito."
  fi
else
  cp AGENTS.md.codex-template AGENTS.md
  echo "Creado AGENTS.md"
fi

chmod +x ai ai-safe ai-status

# Crear rama de trabajo si estamos en main/master y el árbol está limpio.
branch="$(git branch --show-current 2>/dev/null || true)"
if [ "$branch" = "main" ] || [ "$branch" = "master" ]; then
  if [ -z "$(git status --porcelain)" ]; then
    if git show-ref --verify --quiet refs/heads/codex-work; then
      git switch codex-work
    else
      git switch -c codex-work
    fi
    echo "Rama de trabajo activa: codex-work"
  else
    echo "Hay cambios sin guardar. No cambio de rama automáticamente."
  fi
fi

echo
if command -v codex >/dev/null 2>&1; then
  echo "Codex encontrado: $(command -v codex)"
  codex --version || true
else
  echo "Codex CLI no está instalado."
  echo "Instálalo con:"
  echo "  brew install --cask codex"
  echo "o:"
  echo "  npm install -g @openai/codex"
fi

echo
echo "LISTO."
echo "Cuando quieras empezar:"
echo "  ./ai"
echo
echo "Para ver el estado:"
echo "  ./ai-status"
