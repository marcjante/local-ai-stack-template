from pathlib import Path
from typing import Dict, List, Optional

import yaml

from workers.plugin_loader import discover_plugins


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CONFIG_PATH = PROJECT_ROOT / "config" / "tools.yaml"

VALID_EFFECTS = {
    "draft",
    "read",
    "write",
    "read_write",
}


def load_tool_config() -> Dict:
    """Carga y valida config/tools.yaml."""

    if not TOOLS_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"No existe el Tool Registry: {TOOLS_CONFIG_PATH}"
        )

    with TOOLS_CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if data.get("version") != 2:
        raise ValueError(
            "tools.yaml debe utilizar el esquema version 2"
        )

    tools = data.get("tools")

    if not isinstance(tools, list):
        raise ValueError(
            "tools.yaml no contiene una lista válida de tools"
        )

    seen_ids = set()
    seen_queues = set()

    required_fields = {
        "id",
        "queue",
        "enabled",
        "agent_callable",
        "requires_confirmation_before_execute",
        "human_review_required",
        "effect",
        "tasks",
    }

    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError(
                "Cada entrada de tools debe ser un objeto"
            )

        missing = required_fields - set(tool)

        if missing:
            raise ValueError(
                f"Tool incompleta: faltan {sorted(missing)}"
            )

        tool_id = tool["id"]
        queue = tool["queue"]

        if tool_id in seen_ids:
            raise ValueError(
                f"Tool ID duplicado: {tool_id}"
            )

        if queue in seen_queues:
            raise ValueError(
                f"Queue duplicada en Tool Registry: {queue}"
            )

        seen_ids.add(tool_id)
        seen_queues.add(queue)

        for field in (
            "enabled",
            "agent_callable",
            "requires_confirmation_before_execute",
            "human_review_required",
        ):
            if not isinstance(tool[field], bool):
                raise ValueError(
                    f"{tool_id}.{field} debe ser booleano"
                )

        if tool["effect"] not in VALID_EFFECTS:
            raise ValueError(
                f"{tool_id}.effect no válido: "
                f"{tool['effect']}"
            )

        if not isinstance(tool["tasks"], list):
            raise ValueError(
                f"{tool_id}.tasks debe ser una lista"
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
            if tool.get("enabled") is True
        ]

    return tools


def discovered_plugins() -> Dict:
    """
    Devuelve los plugins técnicos disponibles.

    Descubrir un plugin no significa que esté autorizado
    como Tool.
    """

    return discover_plugins()


def list_tools(
    enabled_only: bool = True,
    available_only: bool = True,
    agent_callable_only: bool = False,
) -> List[Dict]:
    """
    Devuelve las Tools autorizadas.

    available_only=True exige que exista realmente
    el plugin correspondiente.

    agent_callable_only=True devuelve únicamente Tools
    que una capa agente está autorizada a solicitar.
    """

    tools = configured_tools(
        enabled_only=enabled_only,
    )

    plugins = discovered_plugins()
    result = []

    for tool in tools:
        item = dict(tool)

        queue_name = item["queue"]
        plugin = plugins.get(queue_name)

        item["available"] = plugin is not None

        if plugin is not None:
            item["module_name"] = plugin.get(
                "module_name"
            )
            item["timeout"] = plugin.get(
                "timeout"
            )
        else:
            item["module_name"] = None
            item["timeout"] = None

        if available_only and not item["available"]:
            continue

        if (
            agent_callable_only
            and not item["agent_callable"]
        ):
            continue

        result.append(item)

    return result


def get_tool(
    tool_id: str,
    require_available: bool = True,
    require_agent_callable: bool = False,
) -> Optional[Dict]:
    """Busca una Tool autorizada por ID."""

    for tool in list_tools(
        enabled_only=True,
        available_only=require_available,
        agent_callable_only=require_agent_callable,
    ):
        if tool["id"] == tool_id:
            return tool

    return None


def tools_for_task(
    task: str,
    require_available: bool = True,
    agent_callable_only: bool = False,
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
        agent_callable_only=agent_callable_only,
    ):
        tasks = [
            str(item).strip().lower()
            for item in tool["tasks"]
        ]

        if task in tasks:
            matches.append(tool)

    return matches


def execution_plan(
    task: str,
    agent_request: bool = True,
) -> Dict:
    """
    Genera un plan informativo de Tools.

    No ejecuta ninguna herramienta.

    Si agent_request=True, solo incluye Tools que
    pueden ser solicitadas por una capa agente.
    """

    tools = tools_for_task(
        task,
        require_available=True,
        agent_callable_only=agent_request,
    )

    return {
        "task": task,
        "agent_request": agent_request,
        "tools": [
            {
                "id": tool["id"],
                "queue": tool["queue"],
                "category": tool.get("category"),
                "available": tool["available"],
                "agent_callable": tool[
                    "agent_callable"
                ],
                "requires_confirmation_before_execute":
                    tool[
                        "requires_confirmation_before_execute"
                    ],
                "human_review_required":
                    tool["human_review_required"],
                "effect": tool["effect"],
                "module_name": tool["module_name"],
                "timeout": tool["timeout"],
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
            f"agent_callable={tool['agent_callable']} "
            f"confirm_before="
            f"{tool['requires_confirmation_before_execute']} "
            f"review_required="
            f"{tool['human_review_required']} "
            f"effect={tool['effect']}"
        )

    print("\nRouting para agente:")

    for task in [
        "protocol_design",
        "search_strategy",
        "pubmed_search",
        "screening",
        "human_screening",
        "rag_query",
    ]:
        plan = execution_plan(
            task,
            agent_request=True,
        )

        print(
            f"\n{task}: "
            f"{[tool['id'] for tool in plan['tools']]}"
        )
