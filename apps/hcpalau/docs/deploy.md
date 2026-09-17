# Desplegament de HC Palau

La imatge Docker d'aquesta aplicació és independent de Local AI Studio. El
directori arrel del servei desplegat ha de ser `apps/hcpalau`.

## Variables obligatòries

Configura-les al panell del proveïdor; no les guardis al repositori:

```text
DATABASE_URL=postgresql://...
ADMIN_TOKEN=<token-aleatori-llarg>
CORS_ORIGINS=https://domini-real.example
```

L'aplicació també accepta els noms `HCPALAU_DATABASE_URL`,
`HCPALAU_ADMIN_TOKEN` i `HCPALAU_CORS_ORIGINS`, que tenen prioritat si hi ha
les dues variants.

Per als vídeos cal un volum persistent o un servei d'objectes. Amb un volum
muntat, configura:

```text
VIDEO_DIR=/data/exercise-videos
```

No facis servir el sistema de fitxers efímer del contenidor per conservar
vídeos.

## Railway amb PostgreSQL

1. Crea un projecte nou i afegeix-hi un servei PostgreSQL gestionat.
2. Afegeix un servei des del repositori Git i selecciona aquesta branca o la
   branca on s'hagi integrat.
3. Configura `apps/hcpalau` com a directori arrel del servei. Railway detectarà
   el `Dockerfile` d'aquest directori.
4. Referencia la URL privada del servei PostgreSQL com a `DATABASE_URL`.
5. Genera un `ADMIN_TOKEN` aleatori i configura `CORS_ORIGINS` amb el domini
   públic final, sense comodí `*`.
6. Configura el healthcheck HTTP a `/ready`.
7. Genera el domini públic i comprova `/health`, `/ready`, `/docs` i `/app/`.
8. Si s'utilitzen vídeos, afegeix un volum persistent, munta'l a `/data` i
   configura `VIDEO_DIR=/data/exercise-videos`.

L'aplicació rebutja l'arrencada amb PostgreSQL si falta `ADMIN_TOKEN`, si es
manté el valor de desenvolupament `dev-admin-token` o si `CORS_ORIGINS` conté
`*`.

Per habilitar el botó de Pizarra-hoquei al portal entrenador, afegeix el
paràmetre URL-encoded `pissarra=https%3A%2F%2F...` a l'enllaç del portal. La
URL s'obre en una pestanya nova i no rep el token d'HC Palau.

Abans del primer trànsit, aplica l'esquema amb `alembic upgrade head` des del
directori arrel del servei. Les migracions són reversibles amb
`alembic downgrade -1`; no s'ha d'editar una migració ja aplicada.

Railway proporciona `PORT`; el contenidor l'utilitza automàticament.
La imatge també declara un `HEALTHCHECK` local contra `/ready`.

## Verificació posterior

```bash
curl -fsS https://domini-real.example/health
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://domini-real.example/auth/session
```

El primer resultat ha de ser:

```json
{"status":"ok","service":"hcpalau"}
```

El segon ha de retornar el rol `admin`. Després crea un jugador des del portal
i comprova el seu enllaç des d'un mòbil fora de la xarxa local.

## Execució local de la imatge

Des de `apps/hcpalau`:

```bash
docker build -t hcpalau .
docker run --rm -p 8000:8000 \
  -e ADMIN_TOKEN=canvia-aquest-token \
  -e DATABASE_URL=sqlite:////tmp/hcpalau.db \
  hcpalau
```

En producció s'ha d'utilitzar PostgreSQL, un token no reutilitzat i HTTPS.

## PostgreSQL local amb Compose

Des de `apps/hcpalau`, sense guardar les variables en un fitxer versionat:

```bash
export POSTGRES_PASSWORD='canvia-aquest-password-local'
export ADMIN_TOKEN='canvia-aquest-token-local'
docker compose up --build
```

Quan `/ready` respongui correctament, obre
`http://127.0.0.1:8000/app/?token=$ADMIN_TOKEN`. Per aturar el servei conserva
el volum de dades amb `docker compose down`, o elimina'l explícitament amb
`docker compose down -v` si vols reiniciar la base local.
