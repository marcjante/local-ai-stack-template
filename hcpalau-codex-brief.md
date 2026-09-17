# Encàrrec per a Codex — HC Palau Infantil D

Treballa de forma autònoma sobre el repositori `hcpalau-app` (ja inicialitzat,
amb backend funcional provat). Segueix l'ordre de tickets tal com estan.
No preguntis abans de començar cada ticket si la informació necessària ja
és en aquest document o a `docs/api-spec.md` — pregunta només quan un
ticket ho digui explícitament.

## 0. Estat actual (ja fet i provat — no ho refacis)

- `backend/`: FastAPI + SQLModel + SQLite per defecte, Postgres opcional
  via `docker-compose.yml`. Arrenca amb `uvicorn app.main:app --reload`.
- Auth: token fix d'admin (`ADMIN_TOKEN`) + token per jugador
  (`Player.access_token`). Verificat amb proves manuals `curl`:
  - Un jugador no pot escriure l'assistència d'un altre (403).
  - Un jugador no pot revertir un objectiu ja marcat `done` (403).
  - Revocar `access_active` bloqueja totes les rutes del jugador a l'instant.
- Endpoints implementats: players, events, attendance, convocations,
  reinforcements, goals, exercises (amb pujada de vídeo mp4/webm ≤30MB),
  routines, exercise-progress, exam-periods, standings, mvp, seguiment,
  notifications (stub).
- `backend/seed.py` puebla 6 jugadors, 7 events de setembre, 21 exercicis
  catalogats i la classificació del grup.
- `frontend/index.html`: la interfície completa, però **encara amb dades
  inventades en memòria (arrays JS)** — no parla amb el backend.
- `whiteboard/README.md`: opcions per integrar `Pizarra-hoquei`/`pz1videos`.
- `integrations/local-ai-stack/sync_fecapa.py`: worker pel patró
  `workers/plugins/` de `local-ai-stack-template`. El parser HTML de la
  FECAPA està sense implementar a propòsit (veure ticket 3).
- `docs/api-spec.md`: especificació completa de referència. Si un ticket
  i aquest document es contradiuen, aquest document mana perquè és el més
  recent.

## Regles que no es poden trencar en cap ticket

- Cap dada de pagaments/quotes/bancària entra en aquest sistema.
- Cap funcionalitat de xat/comunicació interna (l'equip fa servir WhatsApp).
- Un jugador mai llegeix ni escriu dades d'un altre jugador — comprova-ho
  al backend, mai només al frontend.
- L'assignació d'exercicis és sempre individual (jugador a jugador); no
  afegeixis una acció d'"assignar a tot l'equip" sense que t'ho demanin.
- `goals.done` és irreversible des del rol jugador.
- No forcis el domini de HC Palau (jugadors/calendari) dins el concepte de
  "projecte" RAG de `local-ai-stack-template` — són coses diferents.

---

## Ticket 1 — Connectar el frontend al backend real

**Objectiu**: `frontend/index.html` ha de deixar de fer servir els arrays
en memòria (`players`, `events`, `attendance`, `goals`, etc.) i cridar els
endpoints reals amb `fetch()`.

**Fes**:
- Substitueix cada array/objecte en memòria per una crida `fetch()` a
  l'endpoint corresponent (mapeig 1:1, ja documentat a `docs/api-spec.md`).
- El token d'accés (admin o jugador) es llegeix del paràmetre `?token=`
  a la URL (junt amb `?jugador=slug` que ja existeix) i s'envia com a
  header `Authorization: Bearer <token>` a totes les crides.
- Mantén exactament el mateix disseny visual i la mateixa estructura de
  pestanyes — aquest ticket és de cablejat, no de redisseny.
- Els botons que ja fan una acció local (marcar assistència, incrementar
  exercici, marcar objectiu assolit) han de disparar el `PATCH`/`POST`
  corresponent i actualitzar la UI amb la resposta real del servidor, no
  amb l'estat local optimista sense confirmar.
- Si una crida falla (p. ex. 403 per accés revocat), mostra la pantalla
  de "Accés desactivat" que ja existeix al codi, no un error de consola.

**Fet quan**: obrint `frontend/index.html?jugador=biel&token=<token real>`
contra un backend arrencat en local, tot el que es marca es persisteix
(recarregar la pàgina manté els canvis).

## Ticket 2 — Tests automàtics

**Objectiu**: convertir les proves manuals de `curl` que ja s'han fet en
`pytest` reals, perquè no calgui tornar-les a fer a mà cada vegada.

**Fes**: crea `backend/tests/` amb, com a mínim:
- Un jugador no pot escriure attendance d'un altre (403).
- Un jugador no pot revertir un `goal.done` (403).
- `access_active=false` bloqueja totes les rutes `[P]`.
- Pujar un vídeo amb format no permès (p. ex. `.mov`) retorna 400.
- Pujar un vídeo per sobre de 30MB retorna 400.
- L'increment d'`exercise-progress` no supera mai 3 per setmana.
- Usa `TestClient` de FastAPI amb una base SQLite temporal per test
  (no la `hcpalau.db` real).

**Fet quan**: `pytest backend/tests/ -v` passa en verd i cobreix els sis
punts anteriors com a mínim.

## Ticket 3 — Parser real de la FECAPA (bloquejat fins confirmar dades)

**Abans de tocar codi**: pregunta explícitament quina és l'URL pública de
la classificació i de les actes del grup del club a la web de la FECAPA
(o si hi ha credencials d'accés a alguna API privada). No inventis
selectors CSS ni estructura de dades sense haver vist l'HTML/JSON real.

**Un cop tinguis la URL**:
- Implementa `_parse_standings_html()` a
  `integrations/local-ai-stack/sync_fecapa.py`.
- Fes el mateix per a les actes de partit (nou mòdul o funció separada):
  extreu resultat, golejadors, i si l'acta ho detalla, minuts/targetes.
- Cada canvi de format de la pàgina de la federació no ha de trencar res
  més que aquest parser — manté'l aïllat tal com ja està plantejat.
- Actualitza `player_stats` sumant, mai sobreescrivint valors absoluts.

**Fet quan**: executar el worker contra la URL real actualitza `standings`
i `player_stats` sense duplicar dades en execucions repetides.

## Ticket 4 — Notificacions reals (WhatsApp/email)

**Objectiu**: substituir l'stub de `POST /notifications/send/{player_id}/{event_id}`
per un enviament real.

**Abans de tocar codi**: pregunta quin proveïdor vol fer servir el club
(WhatsApp Business API, Twilio, un simple SMTP per correu, etc.) — no
n'assumeixis cap sense confirmar-ho, perquè cadascun requereix credencials
i configuració diferents.

**Fet quan**: enviar una notificació de prova arriba de veritat al mòbil/
correu d'un número de prova, i l'endpoint marca l'enviament com a fet
només si el proveïdor confirma l'entrega (no abans).

## Ticket 5 — Desplegament

**Objectiu**: tenir el backend + frontend accessibles fora de `localhost`,
seguint el mateix patró que ja fas servir a `hcpalau-matchday`
(Railway + SQLite/Postgres gestionat).

**Fes**:
- `DATABASE_URL` apuntant a un Postgres gestionat (Railway, Supabase, o
  el que ja tinguis operatiu).
- Variables d'entorn (`ADMIN_TOKEN`, credencials de vídeo/notificacions)
  gestionades pel panell del proveïdor, mai al codi ni al repo.
- CORS de `backend/app/main.py` restringit al domini real del frontend
  un cop desplegat (ara mateix és `*`, només vàlid per a desenvolupament).
- Documenta els passos exactes a `docs/deploy.md`.

**Fet quan**: un enllaç personal d'un jugador (`https://.../?jugador=biel&token=...`)
funciona des d'un mòbil fora de la xarxa local.

## Ticket 6 — Pissarra tàctica (Opció A del README)

**Objectiu**: afegir una pestanya nova "Pissarra" al frontend (visible
només en mode entrenador) amb un botó que obre `Pizarra-hoquei` en una
pestanya nova, seguint l'Opció A descrita a `whiteboard/README.md`.

**Fet quan**: el botó és visible només per l'entrenador i obre la
pissarra desplegada actual.

---

## Ordre recomanat

1 (frontend real) → 2 (tests, per no trencar el ticket 1 sense adonar-te'n)
→ 5 (desplegament, perquè la resta es pugui provar de debò fora de local)
→ 6 (pissarra, ràpid) → 3 i 4 en paral·lel, cadascun bloquejat fins que
es confirmin les dades externes que demanen.
