# HC Palau API contract

Contracte de referència de l'API implementada a `backend.app.main:app`.
La documentació OpenAPI executable està disponible a `/docs`, `/redoc` i
`/openapi.json` quan el servidor està en marxa.

## Autenticació i rols

Totes les rutes, excepte `GET /health` i la documentació OpenAPI, exigeixen:

```http
Authorization: Bearer <token>
```

Hi ha dos tipus de credencial:

- **A — entrenador/admin**: el token configurat a `HCPALAU_ADMIN_TOKEN`.
- **P — jugador**: el `access_token` individual del jugador, sempre que
  `access_active=true`.

Un token absent o desconegut retorna `401`. Un token vàlid sense permisos,
un slug que no li correspon o un jugador amb accés revocat retorna `403`.
Les comprovacions d'identitat es fan al backend a cada petició.

`access_token` només apareix a les respostes administratives de `/players`;
mai s'inclou al perfil retornat a un jugador.

## Sessió i jugadors

| Mètode | Ruta | Rol | Comportament |
|---|---|---|---|
| `GET` | `/auth/session?jugador={slug}` | A/P | Retorna el rol; per a P retorna només el perfil propi i valida el slug opcional. |
| `POST` | `/players` | A | Crea un jugador amb `slug`, `name` i `access_token`. |
| `GET` | `/players` | A | Llista jugadors, inclosos els tokens necessaris per administrar els enllaços. |
| `GET` | `/players/{player_id}` | A/P propi | Perfil sense token. |
| `PATCH` | `/players/{player_id}/access` | A | Activa o revoca l'accés amb `{ "access_active": bool }`. |

## Calendari, assistència i convocatòries

| Mètode | Ruta | Rol | Comportament |
|---|---|---|---|
| `POST` | `/events` | A | Crea `training`, `match` o `meeting`. |
| `GET` | `/events` | A/P | Llista cronològicament els esdeveniments. |
| `GET` | `/events/{event_id}` | A/P | Retorna un esdeveniment. |
| `GET` | `/attendance/{player_id}` | A/P propi | Llista l'assistència individual. |
| `PATCH` | `/attendance/{event_id}/{player_id}` | A/P propi | Crea o actualitza `{ "attending": bool }`. |
| `PUT` | `/convocations/{event_id}/{player_id}` | A | Convoca individualment amb `selected`, `reserve` o `not_selected`; només per a partits. |
| `GET` | `/convocations/player/{player_id}` | A/P propi | Convocatòries del jugador. |
| `GET` | `/convocations/event/{event_id}` | A | Convocatòria completa del partit. |

## Objectius, exercicis i rutines

| Mètode | Ruta | Rol | Comportament |
|---|---|---|---|
| `POST` | `/goals` | A | Assigna un objectiu a un únic `player_id`. |
| `GET` | `/goals/player/{player_id}` | A/P propi | Objectius individuals. |
| `PATCH` | `/goals/{goal_id}/done` | A/P propietari | Marca `done`; P no pot revertir `true` a `false`. |
| `POST` | `/exercises` | A | Crea un exercici de catàleg. |
| `GET` | `/exercises` | A | Llista el catàleg. |
| `GET` | `/exercises/{exercise_id}` | A/P | Retorna el detall d'un exercici assignat o referenciat. |
| `POST` | `/exercises/{exercise_id}/video` | A | Multipart `video`; només `.mp4`/`.webm`, màxim 30 MB. |
| `POST` | `/exercises/{exercise_id}/assign/{player_id}` | A | Assignació individual; no existeix assignació massiva. |
| `GET` | `/exercises/player/{player_id}` | A/P propi | Assignacions individuals. |
| `POST` | `/exercise-progress/{assignment_id}/increment` | A/P propietari | Incrementa fins a un màxim de 3 per setmana ISO. |
| `GET` | `/exercise-progress/player/{player_id}` | A/P propi | Progrés individual. |
| `POST` | `/routines` | A | Crea una rutina per a un únic `player_id`. |
| `POST` | `/routines/{routine_id}/exercises` | A | Afegeix un exercici, posició i repeticions objectiu. |
| `GET` | `/routines/player/{player_id}` | A/P propi | Rutines individuals. |
| `GET` | `/routines/{routine_id}/exercises` | A/P propietari | Exercicis ordenats de la rutina. |

## Càrrega, seguiment i reconeixements

| Mètode | Ruta | Rol | Comportament |
|---|---|---|---|
| `POST` | `/exam-periods` | A | Crea un període individual; `end_date >= start_date`. |
| `GET` | `/exam-periods/player/{player_id}` | A/P propi | Períodes propis. |
| `DELETE` | `/exam-periods/{period_id}` | A | Elimina un període. |
| `POST` | `/seguiment` | A | Crea una observació individual amb `visible_to_player`. |
| `GET` | `/seguiment/player/{player_id}` | A/P propi | A veu totes les notes; P només les marcades com visibles. |
| `DELETE` | `/seguiment/{follow_up_id}` | A | Elimina una observació. |
| `PUT` | `/mvp/{event_id}/{player_id}` | A | Assigna o corregeix l'únic MVP d'un partit. |
| `GET` | `/mvp/player/{player_id}` | A/P propi | Reconeixements propis. |
| `GET` | `/mvp/event/{event_id}` | A | MVP del partit. |

## Competició i dades administratives

| Mètode | Ruta | Rol | Comportament |
|---|---|---|---|
| `POST` | `/standings` | A | Upsert per temporada/equip; mai duplica l'equip. |
| `GET` | `/standings?season={season}` | A/P | Classificació ordenada per posició. |
| `POST` | `/player-stats/{player_id}/increment` | A | Suma deltes; `source_key` fa la importació idempotent. |
| `GET` | `/player-stats/player/{player_id}?season={season}` | A/P propi | Estadístiques acumulades individuals. |
| `POST` | `/reinforcements` | A | Afegeix un jugador extern a un partit. |
| `GET` | `/reinforcements/event/{event_id}` | A | Llista administrativa de reforços. |
| `PATCH` | `/reinforcements/{reinforcement_id}` | A | Actualitza `{ "confirmed": bool }`. |
| `DELETE` | `/reinforcements/{reinforcement_id}` | A | Elimina un reforç. |

## Sistema i errors

| Mètode | Ruta | Rol | Comportament |
|---|---|---|---|
| `GET` | `/health` | Públic | Retorna `{ "status": "ok", "service": "hcpalau" }`. |
| `GET` | `/ready` | Públic | Comprova que l'aplicació pot consultar la base de dades; retorna `503` si no està preparada. |

Codis habituals:

- `400`: regla de domini invàlida, extensió de vídeo incorrecta o més de 30 MB.
- `401`: falta el Bearer token o és desconegut.
- `403`: rol incorrecte, dades d'un altre jugador o accés revocat.
- `404`: recurs inexistent.
- `409`: duplicat o límit setmanal assolit.
- `422`: cos o paràmetres no vàlids.

## Configuració

| Variable | Valor per defecte | Ús |
|---|---|---|
| `HCPALAU_DATABASE_URL` | `sqlite:///.../hcpalau.db` | SQLite local o URL PostgreSQL. |
| `HCPALAU_ADMIN_TOKEN` | `dev-admin-token` | Token d'entrenador només per a desenvolupament. |
| `HCPALAU_CORS_ORIGINS` | localhost/127.0.0.1 | Orígens permesos, separats per comes. |
| `HCPALAU_VIDEO_DIR` | `uploads/exercises` | Emmagatzematge dels vídeos. |

## Funcionalitats pendents de dades externes

- El parser FECAPA no s'implementa fins disposar de les URL reals de
  classificació i actes o de credencials d'API.
- L'enviament de notificacions no s'implementa fins confirmar el proveïdor
  (WhatsApp Business, Twilio, SMTP o equivalent).
