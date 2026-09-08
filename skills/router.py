from pathlib import Path
from typing import Dict, List, Optional

import yaml


BASE_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = BASE_DIR / "registry.yaml"

TRUST_PRIORITY = {
    "internal": 0,
    "trusted": 1,
    "reviewed": 2,
    "untrusted": 3,
}


def load_registry() -> Dict:
    """Carga y valida el catálogo de skills."""
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(
            f"No existe el Skill Registry: {REGISTRY_PATH}"
        )

    with REGISTRY_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data.get("skills"), list):
        raise ValueError(
            "registry.yaml no contiene una lista válida de skills"
        )

    return data


def list_skills(
    enabled_only: bool = True,
) -> List[Dict]:
    """Devuelve las skills registradas."""

    skills = load_registry()["skills"]

    if enabled_only:
        skills = [
            skill
            for skill in skills
            if skill.get("enabled", True)
        ]

    return skills


def get_skill(skill_id: str) -> Optional[Dict]:
    """Busca una skill por su ID."""

    for skill in list_skills(enabled_only=False):
        if skill.get("id") == skill_id:
            return skill

    return None


def get_trust_level(skill: Dict) -> str:
    """Devuelve el nivel de confianza de una skill."""

    return str(
        skill.get("trust_level", "untrusted")
    ).strip().lower()


def is_external(skill: Dict) -> bool:
    """Indica si la skill procede de una fuente externa."""

    return (
        str(skill.get("origin", "external"))
        .strip()
        .lower()
        != "internal"
    )


def can_execute(skill: Dict) -> bool:
    """
    Indica si una skill puede utilizarse como capacidad ejecutable.

    Las skills externas no revisadas nunca se consideran
    instrucciones ejecutables.
    """

    if is_external(skill):
        return get_trust_level(skill) in {
            "trusted",
            "reviewed",
        }

    return get_trust_level(skill) == "internal"


def skill_mode(skill: Dict) -> str:
    """
    Devuelve cómo debe utilizarse una skill.

    executable:
        Puede formar parte de una capacidad ejecutable.

    reference:
        Solo puede utilizarse como contexto metodológico.
    """

    return "executable" if can_execute(skill) else "reference"


def _priority(skill: Dict) -> tuple:
    """
    Prioriza:
    1. internas
    2. trusted
    3. reviewed
    4. untrusted
    """

    trust = get_trust_level(skill)

    return (
        TRUST_PRIORITY.get(trust, 99),
        str(skill.get("id", "")),
    )


def route_task(
    task: str,
    max_skills: int = 3,
    include_external: bool = True,
) -> List[Dict]:
    """
    Selecciona skills para una tarea.

    El router es determinista y no utiliza LLM.

    Las skills externas no confiables pueden aparecer como
    referencia, pero no se consideran ejecutables.
    """

    task = (task or "").strip().lower()

    if not task:
        return []

    matches = []

    for skill in list_skills():

        if not include_external and is_external(skill):
            continue

        tasks = [
            str(item).strip().lower()
            for item in skill.get("tasks", [])
        ]

        if task in tasks:
            selected = dict(skill)
            selected["runtime_mode"] = skill_mode(skill)
            selected["can_execute"] = can_execute(skill)
            matches.append(selected)

    matches.sort(key=_priority)

    return matches[:max_skills]


def route_task_ids(
    task: str,
    max_skills: int = 3,
    include_external: bool = True,
) -> List[str]:
    """Versión compacta que devuelve solo IDs."""

    return [
        skill["id"]
        for skill in route_task(
            task,
            max_skills=max_skills,
            include_external=include_external,
        )
    ]


def routing_plan(
    task: str,
    max_skills: int = 3,
) -> Dict:
    """
    Genera un plan de routing separado por seguridad.

    executable_skills:
        Skills autorizadas como capacidades ejecutables.

    reference_skills:
        Skills que solo aportan contexto o metodología.
    """

    selected = route_task(
        task,
        max_skills=max_skills,
        include_external=True,
    )

    return {
        "task": task,
        "skills": selected,
        "executable_skills": [
            skill["id"]
            for skill in selected
            if skill["runtime_mode"] == "executable"
        ],
        "reference_skills": [
            skill["id"]
            for skill in selected
            if skill["runtime_mode"] == "reference"
        ],
    }


if __name__ == "__main__":

    print("Skills activas:")

    for skill in list_skills():
        print(
            f"- {skill['id']} "
            f"({skill['category']}) "
            f"[{skill_mode(skill)}]"
        )

    print("\nPrueba de routing:")

    for task in [
        "screening",
        "experimental_design",
        "grounded_theory",
        "manuscript",
        "preregistration",
    ]:
        plan = routing_plan(task)

        print(f"\n{task}")
        print(
            "  ejecutables:",
            plan["executable_skills"],
        )
        print(
            "  referencia:",
            plan["reference_skills"],
        )
