# HC Palau Infantil D

Aplicació independent per a la gestió esportiva de l'equip Infantil D.
Viu sota `apps/hcpalau/` per no barrejar el domini del club amb la
infraestructura genèrica de Local AI Studio.

## Desenvolupament local

```bash
cd apps/hcpalau
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn backend.app.main:app --reload
```

Per defecte crea `hcpalau.db` dins d'aquest directori. Es pot canviar amb
`HCPALAU_DATABASE_URL`. La documentació OpenAPI queda disponible a
`http://127.0.0.1:8000/docs`.

Pots copiar `.env.example` com a referència de les variables disponibles; no
hi posis mai tokens reals al repositori.

El portal del jugador queda servit pel mateix backend a:

```text
http://127.0.0.1:8000/app/?jugador=biel&token=<token-real>
```

El mode entrenador utilitza el token d'administració sense paràmetre de
jugador:

```text
http://127.0.0.1:8000/app/?token=<HCPALAU_ADMIN_TOKEN>
```

La integració Opció A amb la pissarra tàctica externa es configura afegint la
URL desplegada a l'enllaç de l'entrenador:

```text
http://127.0.0.1:8000/app/?token=<HCPALAU_ADMIN_TOKEN>&pissarra=https%3A%2F%2Fpissarra.example
```

Només s'accepten URLs `http` o `https`; el token d'HC Palau no es reenvia a
la pissarra.

Per tenir dades de prova locals (sis jugadors, calendari, exercicis, rutina i
classificació):

```bash
python -m backend.seed
```

La comanda és idempotent i rebutja bases de dades no SQLite per defecte.

Per aplicar les migracions explícitament:

```bash
alembic upgrade head
```

El worker FECAPA de la temporada 2026/27 usa per defecte el grup Infantil OR
9 i es pot executar així:

```bash
python -m integrations.local_ai_stack.sync_fecapa
python -m integrations.local_ai_stack.sync_fecapa --persist --season 2026-27
python -m integrations.local_ai_stack.sync_fecapa --actas-only
```

El segon mode retorna una llista buida fins que la federació publica les actes.

El polling del panell entrenador és de 8 segons; es pot ajustar entre 5 i 60
segons amb `?poll=15`.

El contracte funcional, els rols i els endpoints també estan documentats a
[`docs/api-spec.md`](docs/api-spec.md).

La preparació de contenidor i els passos de desplegament són a
[`docs/deploy.md`](docs/deploy.md).

Per provar PostgreSQL localment amb Docker Compose, defineix `POSTGRES_PASSWORD`
i `ADMIN_TOKEN` a l'entorn i executa `docker compose up --build`.

## Proves

```bash
cd apps/hcpalau
pytest -v
```

També hi ha dreceres equivalents a `Makefile`: `make install` (crea `.venv` i
instal·la dependències), `make test`, `make run`, `make migrate` i `make seed`.

No s'hi gestionen pagaments ni dades bancàries, i l'aplicació no inclou
funcions de xat.
