"""
evaluation.py

Framework de evaluación GENÉRICO: no sabe nada de ningún dominio
concreto. Compara la salida de cualquier función contra lo que se espera,
usando un puñado de comprobaciones simples y componibles. Sirve tanto
para evaluar el RAG (¿el documento correcto sale entre los resultados?)
como un worker completo (¿el veredicto fue el esperado?), o cualquier
otra función del proyecto que lo use.

Formato de un caso (dict):
    {
        "id": "identificador único",
        "input": {...},                          # lo que se le pasa al handler
        "expect_contains": "texto",               # opcional: ese texto debe aparecer en la salida (case-insensitive)
        "expect_field": {"path": "a.b.c", "equals": valor},  # opcional: campo exacto (notación con puntos)
        "expect_min_score": {"path": "a.b", "min": 0.5},     # opcional: campo numérico por encima de un umbral
    }

Un caso puede combinar varias comprobaciones — pasa solo si TODAS pasan.
"""

import json


def _get_path(obj, path: str):
    """Navega 'a.b.c' dentro de un dict/list anidado. None si no existe."""
    current = obj
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def evaluate_case(case: dict, handler) -> dict:
    """Ejecuta un caso contra `handler` (función que acepta case['input']) y compara."""
    try:
        output = handler(case["input"])
    except Exception as e:
        return {"id": case.get("id"), "passed": False, "error": str(e), "checks": []}

    checks = []

    if "expect_contains" in case:
        haystack = json.dumps(output, ensure_ascii=False).lower()
        needle = case["expect_contains"].lower()
        checks.append({
            "check": "contains", "expected": case["expect_contains"],
            "passed": needle in haystack,
        })

    if "expect_field" in case:
        spec = case["expect_field"]
        actual = _get_path(output, spec["path"])
        checks.append({
            "check": "field_equals", "path": spec["path"],
            "expected": spec["equals"], "actual": actual,
            "passed": actual == spec["equals"],
        })

    if "expect_min_score" in case:
        spec = case["expect_min_score"]
        actual = _get_path(output, spec["path"])
        passed = isinstance(actual, (int, float)) and actual >= spec["min"]
        checks.append({
            "check": "min_score", "path": spec["path"],
            "expected_min": spec["min"], "actual": actual, "passed": passed,
        })

    passed = bool(checks) and all(c["passed"] for c in checks)
    return {"id": case.get("id"), "passed": passed, "checks": checks, "output": output}


def run_suite(cases: list, handler) -> dict:
    """Ejecuta todos los casos y devuelve un resumen + detalle por caso."""
    results = [evaluate_case(c, handler) for c in cases]
    n_passed = sum(1 for r in results if r["passed"])
    n_total = len(results)
    return {
        "total": n_total,
        "passed": n_passed,
        "failed": n_total - n_passed,
        "pass_rate": round(n_passed / n_total, 3) if n_total else 0.0,
        "results": results,
    }
