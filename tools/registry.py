from pathlib import Path
from typing import Dict, List, Optional

import yaml

from workers.plugin_loader import discover_plugins


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CONFIG_PATH = PROJECT_ROOT / "config" / "tools.yaml"


def load_tool_config() -> Dict:
    """Carga y valida config/tools.yaml."""

    if not TOOLS_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"No existe el Tool Registry: {TOOLS_CONFIG_PATH}"
        )

    with TOOLS_CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data.get("tools"), list):
        raise ValueError(
            "tools.yaml no contiene una lista válida de tools"
        )

    return data


def configured_tools(
    enabled_only: bool = True,
) -> List[Dict]:
    """Devuelve las Tools declaradas en la lista blanca."""

    tools = load_tool_config()["tools"]

    if enabled_only:
        tools = [
            tool
            for tool in tools
            if tool.get("enabled", True)
        ]

    return tools


def discovered_plugins() -> Dict:
    """
    Devuelve los plugins técnicos disponibles.

    Descubrir un plugin NO significa que esté autorizado
    como Tool para el agente.
    """

    return discover_plugins()


def list_tools(
    enabled_only: bool = True,
    available_only: bool = True,
) -> List[Dict]:
    """
    Devuelve las Tools autorizadas.

    available_only=True exige además que exista realmente
    el plugin/queue correspondiente.
    """

    tools = configured_tools(
        enabled_only=enabled_only,
    )

    plugins = discovered_plugins()

    result = []

    for tool in tools:
        item = dict(tool)
        queue_name = item.get("queue")
        plugin = plugins.get(queue_name)

        item["available"] = plugin is not None

        if plugin is not None:
            item["module_name"] = plugin.get("module_name")
            item["timeout"] = plugin.get("timeout")
        else:
            item["module_name"] = None
            item["timeout"] = None

        if available_only and not item["available"]:
            continue

        result.append(item)

    return result


def get_tool(
    tool_id: str,
    require_available: bool = True,
) -> Optional[Dict]:
    """Busca una Tool autorizada por ID."""

    for tool in list_tools(
        enabled_only=True,
        available_only=require_available,
    ):
        if tool.get("id") == tool_id:
            return tool

    return None


def tools_for_task(
    task: str,
    require_available: bool = True,
) -> List[Dict]:
    """
    Devuelve las Tools autorizadas asociadas
    explícitamente a una tarea.
    """

    task = (task or "").strip().lower()

    if not task:
        return []

    matches = []

    for tool in list_tools(
        enabled_only=True,
        available_only=require_available,
    ):
        tasks = [
            str(item).strip().lower()
            for item in tool.get("tasks", [])
        ]

        if task in tasks:
            matches.append(tool)

    return matches


def execution_plan(task: str) -> Dict:
    """
    Genera un plan informativo de Tools.

    No ejecuta ninguna herramienta.
    """

    tools = tools_for_task(task)

    return {
        "task": task,
        "tools": [
            {
                "id": tool.get("id"),
                "queue": tool.get("queue"),
                "category": tool.get("category"),
                "available": tool.get("available"),
                "human_confirmation": tool.get(
                    "human_confirmation",
                    True,
                ),
                "module_name": tool.get("module_name"),
                "timeout": tool.get("timeout"),
            }
            for tool in tools
        ],
    }


if __name__ == "__main__":

    print("Tools autorizadas:\n")

    for tool in list_tools():
        print(
            f"- {tool['id']} "
            f"-> queue={tool['queue']} "
            f"available={tool['available']} "
            f"human_confirmation="
            f"{tool.get('human_confirmation', True)}"
        )

    print("\nPrueba por tarea:")

    for task in [
        "protocol_design",
        "search_strategy",
        "pubmed_search",
        "screening",
        "human_screening",
        "rag_query",
    ]:
        plan = execution_plan(task)
        print(
            f"\n{task}: "
            f"{[tool['id'] for tool in plan['tools']]}"
        )
