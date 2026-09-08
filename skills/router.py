from pathlib import Path
from typing import Dict, List, Optional

import yaml


BASE_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = BASE_DIR / "registry.yaml"


def load_registry() -> Dict:
    """Carga el catálogo de skills."""
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(
            f"No existe el Skill Registry: {REGISTRY_PATH}"
        )

    with REGISTRY_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
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


def get_skill(
    skill_id: str,
) -> Optional[Dict]:
    """Busca una skill por su ID."""

    for skill in list_skills(
        enabled_only=False
    ):
        if skill.get("id") == skill_id:
            return skill

    return None


def route_task(
    task: str,
    max_skills: int = 3,
) -> List[Dict]:
    """
    Selecciona las skills necesarias para una tarea.

    El router es determinista:
    no utiliza LLM y no carga todas las skills.
    """

    task = (task or "").strip().lower()

    if not task:
        return []

    matches = []

    for skill in list_skills():

        tasks = [
            str(item).strip().lower()
            for item in skill.get("tasks", [])
        ]

        if task in tasks:
            matches.append(skill)

    return matches[:max_skills]


def route_task_ids(
    task: str,
    max_skills: int = 3,
) -> List[str]:
    """Versión compacta que devuelve solo IDs."""

    return [
        skill["id"]
        for skill in route_task(
            task,
            max_skills=max_skills,
        )
    ]


if __name__ == "__main__":

    print("Skills activas:")
    for skill in list_skills():
        print(
            f"- {skill['id']} "
            f"({skill['category']})"
        )

    print("\nPrueba de routing:")
    for task in [
        "screening",
        "experimental_design",
        "grounded_theory",
        "manuscript",
        "preregistration",
    ]:
        print(
            f"{task}: "
            f"{route_task_ids(task)}"
        )
