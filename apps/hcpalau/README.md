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

El portal del jugador queda servit pel mateix backend a:

```text
http://127.0.0.1:8000/app/?jugador=biel&token=<token-real>
```

El mode entrenador utilitza el token d'administració sense paràmetre de
jugador:

```text
http://127.0.0.1:8000/app/?token=<HCPALAU_ADMIN_TOKEN>
```

El contracte funcional, els rols i els endpoints també estan documentats a
[`docs/api-spec.md`](docs/api-spec.md).

## Proves

```bash
cd apps/hcpalau
pytest -v
```

No s'hi gestionen pagaments ni dades bancàries, i l'aplicació no inclou
funcions de xat.
