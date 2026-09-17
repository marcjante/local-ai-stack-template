"use strict";

const params = new URLSearchParams(window.location.search);
const token = params.get("token") || "";
const jugador = params.get("jugador") || "";
const API_BASE = (params.get("api") || window.location.origin).replace(/\/$/, "");
const whiteboardCandidate = params.get("pissarra") || "https://marcjante.github.io/Pizarra-hoquei/";
const whiteboardUrl = /^https?:\/\//i.test(whiteboardCandidate) ? whiteboardCandidate : "";
const requestedPollSeconds = Number(params.get("poll"));
const adminPollMs = Number.isFinite(requestedPollSeconds) && requestedPollSeconds >= 5 && requestedPollSeconds <= 60
  ? requestedPollSeconds * 1000 : 8000;
const now = new Date();
const seasonStart = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
const season = params.get("season") || `${seasonStart}-${String(seasonStart + 1).slice(-2)}`;

const state = { player: null, attendance: new Map(), progress: new Map(), convocations: new Map() };
let adminLoadInFlight = false;
const dateFormat = new Intl.DateTimeFormat("ca-ES", { dateStyle: "medium", timeStyle: "short" });

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch (_) {
    throw new Error("access");
  }
  if (!response.ok) throw new Error("access");
  if (response.status === 204) return null;
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[char]);
}

function empty(message) { return `<div class="empty">${escapeHtml(message)}</div>`; }

function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  window.setTimeout(() => toast.classList.add("hidden"), 2200);
}

function showAccessDisabled() {
  document.querySelector("#loading").classList.add("hidden");
  document.querySelector("#portal").classList.add("hidden");
  document.querySelector("#admin-portal").classList.add("hidden");
  document.querySelector("#access-disabled").classList.remove("hidden");
}

function adminToast(message) {
  const toast = document.querySelector("#admin-toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  window.setTimeout(() => toast.classList.add("hidden"), 2200);
}

function setupWhiteboard() {
  const link = document.querySelector("#whiteboard-link");
  const help = document.querySelector("#whiteboard-help");
  if (whiteboardUrl) {
    link.href = whiteboardUrl;
    link.removeAttribute("aria-disabled");
    help.textContent = "Pissarra configurada. S'obre en una pestanya nova i no comparteix el token d'HC Palau.";
    return;
  }
  link.classList.add("disabled");
  link.addEventListener("click", event => event.preventDefault());
  help.textContent = "Configura ?pissarra=https://... a l'enllaç de l'entrenador per obrir la pissarra desplegada.";
}

function playerLink(player) {
  const url = new URL("./", window.location.href);
  url.search = new URLSearchParams({ jugador: player.slug, token: player.access_token });
  return url.toString();
}

function renderAdminPlayers(players) {
  const target = document.querySelector("#admin-players");
  target.innerHTML = players.length ? players.map(player => `<article class="card player-card">
    <div><p class="meta">${player.access_active ? "Accés actiu" : "Accés desactivat"}</p><h3>${escapeHtml(player.name)}</h3><p>@${escapeHtml(player.slug)}</p></div>
    <div class="actions">
      <a class="action link" href="${escapeHtml(playerLink(player))}" target="_blank" rel="noopener">Obrir enllaç</a>
      <button class="action" data-access="${player.id}" data-active="${!player.access_active}">${player.access_active ? "Desactivar" : "Activar"}</button>
    </div>
  </article>`).join("") : empty("Encara no hi ha jugadors.");
  target.querySelectorAll("[data-access]").forEach(button => button.addEventListener("click", async () => {
    try {
      await api(`/players/${button.dataset.access}/access`, { method: "PATCH", body: JSON.stringify({ access_active: button.dataset.active === "true" }) });
      await loadAdmin(); adminToast("Accés actualitzat");
    } catch (_) { showAccessDisabled(); }
  }));
  const options = players.map(player => `<option value="${player.id}">${escapeHtml(player.name)}</option>`).join("");
  document.querySelector("#goal-form select[name=player_id]").innerHTML = options;
}

function renderAdminEvents(events) {
  document.querySelector("#admin-events").innerHTML = events.length ? events.map(event => `<article class="card">
    <p class="meta">${escapeHtml(dateFormat.format(new Date(event.starts_at)))}</p><h4>${escapeHtml(event.title)}</h4><p>${escapeHtml(event.location || "Sense ubicació")}</p>
  </article>`).join("") : empty("No hi ha esdeveniments.");
}

function renderAdminActivity(items) {
  document.querySelector("#admin-activity").innerHTML = items.length ? items.map(item => `<article class="card"><p class="meta">${escapeHtml(dateFormat.format(new Date(item.updated_at)))}</p><strong>${escapeHtml(item.player)}</strong><p>${item.kind === "attendance" ? `Assistència: ${item.value ? "sí" : "no"}` : `Exercici: ${item.value}/3`}</p><p>${escapeHtml(item.label)}</p></article>`).join("") : empty("Encara no hi ha actualitzacions dels jugadors.");
}

function renderAdminExercises(exercises, players) {
  document.querySelector("#admin-exercises").innerHTML = exercises.length ? exercises.map(exercise => `<article class="card">
    <p class="meta">${exercise.video_filename ? "Vídeo disponible" : "Sense vídeo"}</p>
    <h4>${escapeHtml(exercise.title)}</h4><p>${escapeHtml(exercise.description || "")}</p>
  </article>`).join("") : empty("Encara no hi ha exercicis al catàleg.");
  const exerciseOptions = exercises.map(exercise => `<option value="${exercise.id}">${escapeHtml(exercise.title)}</option>`).join("");
  document.querySelector("#assignment-form select[name=exercise_id]").innerHTML = exerciseOptions;
  document.querySelector("#video-form select[name=exercise_id]").innerHTML = exerciseOptions;
  document.querySelector("#assignment-form select[name=player_id]").innerHTML = players.map(player => `<option value="${player.id}">${escapeHtml(player.name)}</option>`).join("");
}

function renderAdminCompetition(players, events) {
  const matches = events.filter(event => event.event_type === "match");
  const matchOptions = matches.map(event => `<option value="${event.id}">${escapeHtml(event.title)} · ${escapeHtml(dateFormat.format(new Date(event.starts_at)))}</option>`).join("");
  const playerOptions = players.map(player => `<option value="${player.id}">${escapeHtml(player.name)}</option>`).join("");
  ["#convocation-form", "#mvp-form"].forEach(selector => {
    document.querySelector(`${selector} select[name=event_id]`).innerHTML = matchOptions;
    document.querySelector(`${selector} select[name=player_id]`).innerHTML = playerOptions;
  });
  document.querySelector("#reinforcement-form select[name=event_id]").innerHTML = matchOptions;
}

function renderAdminPlanning(players, exercises, routines) {
  const playerOptions = players.map(player => `<option value="${player.id}">${escapeHtml(player.name)}</option>`).join("");
  ["#routine-form", "#exam-form", "#follow-up-form"].forEach(selector => {
    document.querySelector(`${selector} select[name=player_id]`).innerHTML = playerOptions;
  });
  document.querySelector("#routine-exercise-form select[name=routine_id]").innerHTML = routines.map(routine => `<option value="${routine.id}">${escapeHtml(routine.title)} · ${escapeHtml(routine.player_name)}</option>`).join("");
  document.querySelector("#routine-exercise-form select[name=exercise_id]").innerHTML = exercises.map(exercise => `<option value="${exercise.id}">${escapeHtml(exercise.title)}</option>`).join("");
}

function renderStandings(rows, targetSelector = "#standings-body") {
  const target = document.querySelector(targetSelector);
  const detailed = targetSelector === "#standings-body";
  target.innerHTML = rows.length ? rows.map(row => `<tr><td>${row.position}</td><td class="standing-team">${escapeHtml(row.team)}</td><td>${row.played}</td>${detailed ? `<td>${row.won}</td><td>${row.drawn}</td><td>${row.lost}</td>` : ""}<td>${row.points}</td></tr>`).join("") : `<tr><td colspan="${detailed ? 7 : 4}">Encara no hi ha classificació disponible.</td></tr>`;
}

async function loadAdmin() {
  if (adminLoadInFlight) return;
  adminLoadInFlight = true;
  try {
  const [players, events, exercises, standings, activity] = await Promise.all([api("/players"), api("/events"), api("/exercises"), api(`/standings?season=${encodeURIComponent(season)}`), api("/activity")]);
  const routineGroups = await Promise.all(players.map(player => api(`/routines/player/${player.id}`)));
  const routines = routineGroups.flatMap((items, index) => items.map(item => ({ ...item, player_name: players[index].name })));
  renderAdminPlayers(players); renderAdminEvents(events); renderAdminExercises(exercises, players); renderAdminCompetition(players, events); renderAdminPlanning(players, exercises, routines);
  renderStandings(standings, "#admin-standings-body");
  renderAdminActivity(activity);
  } finally {
    adminLoadInFlight = false;
  }
}

function setupAdminForms() {
  document.querySelector("#standing-form input[name=season]").value = season;
  document.querySelector("#player-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/players", { method: "POST", body: JSON.stringify(Object.fromEntries(form)) });
      event.currentTarget.reset(); await loadAdmin(); adminToast("Jugador creat");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#event-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    form.starts_at = new Date(form.starts_at).toISOString();
    try {
      await api("/events", { method: "POST", body: JSON.stringify(form) });
      event.currentTarget.reset(); await loadAdmin(); adminToast("Esdeveniment creat");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#goal-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    form.player_id = Number(form.player_id);
    try {
      await api("/goals", { method: "POST", body: JSON.stringify(form) });
      event.currentTarget.reset(); adminToast("Objectiu assignat");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#exercise-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api("/exercises", { method: "POST", body: JSON.stringify(form) });
      event.currentTarget.reset(); await loadAdmin(); adminToast("Exercici creat");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#assignment-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api(`/exercises/${form.exercise_id}/assign/${form.player_id}`, { method: "POST" });
      adminToast("Exercici assignat al jugador");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#video-form").addEventListener("submit", async event => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const exerciseId = fields.get("exercise_id");
    const upload = new FormData();
    upload.set("video", fields.get("video"));
    try {
      await api(`/exercises/${exerciseId}/video`, { method: "POST", body: upload });
      event.currentTarget.reset(); await loadAdmin(); adminToast("Vídeo pujat");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#convocation-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    const path = `/convocations/${form.event_id}/${form.player_id}`;
    delete form.event_id; delete form.player_id;
    try {
      await api(path, { method: "PUT", body: JSON.stringify(form) });
      adminToast("Convocatòria desada");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#mvp-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    const path = `/mvp/${form.event_id}/${form.player_id}`;
    const body = { note: form.note };
    try {
      await api(path, { method: "PUT", body: JSON.stringify(body) });
      adminToast("MVP actualitzat");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#reinforcement-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    form.event_id = Number(form.event_id);
    try {
      await api("/reinforcements", { method: "POST", body: JSON.stringify(form) });
      event.currentTarget.reset(); await loadAdmin(); adminToast("Reforç afegit");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#routine-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    form.player_id = Number(form.player_id);
    try {
      await api("/routines", { method: "POST", body: JSON.stringify(form) });
      event.currentTarget.reset(); await loadAdmin(); adminToast("Rutina creada");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#routine-exercise-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    const routineId = form.routine_id;
    delete form.routine_id;
    form.exercise_id = Number(form.exercise_id);
    form.position = Number(form.position);
    form.target_repetitions = Number(form.target_repetitions);
    try {
      await api(`/routines/${routineId}/exercises`, { method: "POST", body: JSON.stringify(form) });
      adminToast("Exercici afegit a la rutina");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#exam-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    form.player_id = Number(form.player_id);
    try {
      await api("/exam-periods", { method: "POST", body: JSON.stringify(form) });
      event.currentTarget.reset(); await loadAdmin(); adminToast("Període registrat");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#follow-up-form").addEventListener("submit", async event => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const form = Object.fromEntries(fields);
    form.player_id = Number(form.player_id);
    form.visible_to_player = fields.has("visible_to_player");
    try {
      await api("/seguiment", { method: "POST", body: JSON.stringify(form) });
      event.currentTarget.reset(); await loadAdmin(); adminToast("Seguiment desat");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#standing-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    ["position", "played", "won", "drawn", "lost", "goals_for", "goals_against", "points"].forEach(field => { form[field] = Number(form[field]); });
    try {
      await api("/standings", { method: "POST", body: JSON.stringify(form) });
      await loadAdmin(); adminToast("Classificació actualitzada");
    } catch (_) { showAccessDisabled(); }
  });
}

async function startAdmin() {
  setupAdminForms();
  setupWhiteboard();
  await loadAdmin();
  window.setInterval(() => {
    if (!document.activeElement?.closest("form")) loadAdmin().catch(() => {});
  }, adminPollMs);
  document.querySelector("#loading").classList.add("hidden");
  document.querySelector("#admin-portal").classList.remove("hidden");
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach(button => button.addEventListener("click", () => {
    document.querySelectorAll(".tab, .panel").forEach(element => element.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.tab}`).classList.add("active");
  }));
}

function renderEvents(events) {
  const target = document.querySelector("#events-list");
  target.innerHTML = events.length ? events.map(event => {
    const attendance = state.attendance.get(event.id);
    const convocation = state.convocations.get(event.id);
    const type = { training: "Entrenament", match: "Partit", meeting: "Reunió" }[event.event_type];
    const callup = convocation ? { selected: "Convocat", reserve: "Reserva", not_selected: "No convocat" }[convocation.selection_status] : "";
    return `<article class="card">
      <p class="meta">${escapeHtml(type)} · ${escapeHtml(dateFormat.format(new Date(event.starts_at)))}</p>
      <h3>${escapeHtml(event.title)}</h3>
      <p>${escapeHtml(event.location || "Ubicació per confirmar")}</p>
      ${callup ? `<span class="callup">${escapeHtml(callup)}</span>` : ""}
      <div class="actions">
        <button class="action ${attendance?.attending === true ? "primary" : ""}" data-attendance="${event.id}" data-value="true">Hi aniré</button>
        <button class="action ${attendance?.attending === false ? "primary" : ""}" data-attendance="${event.id}" data-value="false">No hi podré anar</button>
      </div>
    </article>`;
  }).join("") : empty("No hi ha esdeveniments programats.");

  target.querySelectorAll("[data-attendance]").forEach(button => button.addEventListener("click", async () => {
    try {
      const saved = await api(`/attendance/${button.dataset.attendance}/${state.player.id}`, {
        method: "PATCH", body: JSON.stringify({ attending: button.dataset.value === "true" })
      });
      state.attendance.set(saved.event_id, saved);
      renderEvents(events);
      showToast("Assistència desada");
    } catch (_) { showAccessDisabled(); }
  }));
}

function renderGoals(goals) {
  const target = document.querySelector("#goals-list");
  target.innerHTML = goals.length ? goals.map(goal => `<article class="card ${goal.done ? "done" : ""}">
    <p class="meta">${goal.done ? "Assolit" : "En curs"}</p>
    <h3>${escapeHtml(goal.title)}</h3><p>${escapeHtml(goal.description || "")}</p>
    ${goal.done ? "" : `<div class="actions"><button class="action primary" data-goal="${goal.id}">Marcar com assolit</button></div>`}
  </article>`).join("") : empty("Encara no tens cap objectiu assignat.");
  target.querySelectorAll("[data-goal]").forEach(button => button.addEventListener("click", async () => {
    try {
      const saved = await api(`/goals/${button.dataset.goal}/done`, { method: "PATCH", body: JSON.stringify({ done: true }) });
      const index = goals.findIndex(goal => goal.id === saved.id);
      goals[index] = saved;
      renderGoals(goals);
      showToast("Objectiu assolit!");
    } catch (_) { showAccessDisabled(); }
  }));
}

async function renderTraining(assignments, routines) {
  const exercises = await Promise.all(assignments.map(item => api(`/exercises/${item.exercise_id}`)));
  const exerciseTarget = document.querySelector("#exercises-list");
  exerciseTarget.innerHTML = assignments.length ? assignments.map((assignment, index) => {
    const progress = state.progress.get(assignment.id)?.repetitions || 0;
    return `<article class="card"><p class="meta">${progress}/3 aquesta setmana</p>
      <h3>${escapeHtml(exercises[index].title)}</h3><p>${escapeHtml(exercises[index].description || "")}</p>
      <div class="actions"><button class="action primary" data-progress="${assignment.id}" ${progress >= 3 ? "disabled" : ""}>He practicat</button></div>
    </article>`;
  }).join("") : empty("Encara no tens exercicis assignats.");
  exerciseTarget.querySelectorAll("[data-progress]").forEach(button => button.addEventListener("click", async () => {
    try {
      const saved = await api(`/exercise-progress/${button.dataset.progress}/increment`, { method: "POST" });
      state.progress.set(saved.assignment_id, saved);
      await renderTraining(assignments, routines);
      showToast("Progrés actualitzat");
    } catch (_) { showAccessDisabled(); }
  }));

  const routineTarget = document.querySelector("#routines-list");
  routineTarget.innerHTML = routines.length ? routines.map(routine => `<article class="card"><h4>${escapeHtml(routine.title)}</h4><p>${routine.active ? "Rutina activa" : "Rutina finalitzada"}</p></article>`).join("") : empty("No hi ha rutines actives.");
}

function renderProgress(stats, followUp, exams, mvp) {
  const totals = stats.reduce((sum, row) => ({ games: sum.games + row.games, goals: sum.goals + row.goals, assists: sum.assists + row.assists }), { games: 0, goals: 0, assists: 0 });
  document.querySelector("#metrics").innerHTML = [
    [totals.games, "Partits"], [totals.goals, "Gols"], [totals.assists, "Assistències"], [mvp.length, "MVP"]
  ].map(([value, label]) => `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`).join("");
  document.querySelector("#follow-up-list").innerHTML = followUp.length ? followUp.map(item => `<article class="card"><p class="meta">${escapeHtml(item.observed_on)} · ${escapeHtml(item.category)}</p><p>${escapeHtml(item.note)}</p></article>`).join("") : empty("Encara no hi ha observacions compartides.");
  document.querySelector("#exam-list").innerHTML = exams.length ? exams.map(item => `<article class="card"><h4>${escapeHtml(item.start_date)} — ${escapeHtml(item.end_date)}</h4><p>${escapeHtml(item.note || "Període d'exàmens")}</p></article>`).join("") : empty("No tens períodes d'exàmens registrats.");
}

async function start() {
  if (!token) return showAccessDisabled();
  try {
    const sessionPath = jugador ? `/auth/session?jugador=${encodeURIComponent(jugador)}` : "/auth/session";
    const session = await api(sessionPath);
    if (session.role === "admin") return await startAdmin();
    if (!jugador || session.role !== "player" || !session.player) return showAccessDisabled();
    state.player = session.player;
    const id = state.player.id;
    const [events, attendance, goals, assignments, progress, routines, stats, followUp, exams, mvp, convocations, standings] = await Promise.all([
      api("/events"), api(`/attendance/${id}`), api(`/goals/player/${id}`),
      api(`/exercises/player/${id}`), api(`/exercise-progress/player/${id}`),
      api(`/routines/player/${id}`), api(`/player-stats/player/${id}`),
      api(`/seguiment/player/${id}`), api(`/exam-periods/player/${id}`), api(`/mvp/player/${id}`),
      api(`/convocations/player/${id}`), api(`/standings?season=${encodeURIComponent(season)}`)
    ]);
    attendance.forEach(item => state.attendance.set(item.event_id, item));
    progress.forEach(item => state.progress.set(item.assignment_id, item));
    convocations.forEach(item => state.convocations.set(item.event_id, item));
    document.querySelector("#welcome").textContent = `Hola, ${state.player.name}`;
    renderEvents(events); renderGoals(goals); await renderTraining(assignments, routines);
    renderProgress(stats, followUp, exams, mvp);
    document.querySelector("#season-label").textContent = `Temporada ${season}`;
    renderStandings(standings);
    setupTabs();
    document.querySelector("#loading").classList.add("hidden");
    document.querySelector("#portal").classList.remove("hidden");
  } catch (_) { showAccessDisabled(); }
}

start();
