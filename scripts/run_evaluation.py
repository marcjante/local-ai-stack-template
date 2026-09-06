"""
run_evaluation.py

Ejecuta un fichero de casos (JSON) contra un "target" y saca un informe
en la terminal. No sabe nada de ningún dominio concreto — funciona igual
para el RAG que para cualquier worker plugin.

Uso:
    python3 scripts/run_evaluation.py --cases evaluation/cases_rag_example.json --target rag
    python3 scripts/run_evaluation.py --cases mis_casos.json --target plugin:process

Para el target "rag", cada caso.input es {"query": "...", "top_k": N} y
la salida que se compara es {"results": [chunks tras rerank + citas]}.

Para "plugin:<nombre>", cada caso.input es el `payload` que recibiría
ese worker (igual que si viniera del backend), y se ejecuta su
handle() de verdad — incluida escritura real en Postgres, así que
requiere que Redis/Postgres estén levantados igual que en producción.
"""

import argparse
import importlib
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.evaluation import run_suite  # noqa: E402


def make_rag_handler(project_id: str = None):
    from rag.retrieval import retrieve
    from rag.rerank import rerank
    from rag.citations import format_citations

    def handler(input_data):
        query = input_data["query"]
        top_k = input_data.get("top_k", 5)
        candidates = retrieve(query, top_k=20, project_id=project_id)
        top = rerank(query, candidates, top_n=top_k)
        return {"results": format_citations(top)}

    return handler


def make_plugin_handler(plugin_name):
    module = importlib.import_module(f"workers.plugins.{plugin_name}")

    def handler(input_data):
        task_id = f"eval-{uuid.uuid4()}"
        return module.handle(task_id, input_data)

    return handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, help="Fichero JSON con la lista de casos")
    parser.add_argument("--target", required=True, help="'rag' o 'plugin:<nombre>'")
    parser.add_argument("--project", default=None, help="project_id para acotar el RAG y registrar el resultado (opcional)")
    args = parser.parse_args()

    with open(args.cases, encoding="utf-8") as f:
        cases = json.load(f)

    if args.target == "rag":
        handler = make_rag_handler(project_id=args.project)
    elif args.target.startswith("plugin:"):
        handler = make_plugin_handler(args.target.split(":", 1)[1])
    else:
        print(f"Target desconocido: {args.target} (usa 'rag' o 'plugin:<nombre>')")
        sys.exit(1)

    summary = run_suite(cases, handler)

    print(f"\n{summary['passed']}/{summary['total']} casos pasados ({summary['pass_rate']*100:.0f}%)\n")
    for r in summary["results"]:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        print(f"{status}  {r['id']}")
        if r.get("error"):
            print(f"        error: {r['error']}")
        for c in r.get("checks", []):
            if not c["passed"]:
                print(f"        falló: {c}")

    if args.project:
        from db.db import record_evaluation_run
        record_evaluation_run(args.project, args.target, Path(args.cases).name, summary)
        print(f"\n(resultado guardado para el proyecto '{args.project}')")

    sys.exit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
