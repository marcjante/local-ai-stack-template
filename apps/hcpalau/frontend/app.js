"use strict";

const params = new URLSearchParams(window.location.search);
const jugador = params.get("jugador") || "";
// La pestaña de l'entrenador és una entrada directa de l'equip. Els enllaços
// de jugador continuen exigint el seu token individual.
const token = params.get("token") || (jugador ? "" : "3304e472fc3051b2dd90d292a1e2e50f4f625d65941b7db7764c60ad653779fb");
const API_BASE = (params.get("api") || window.location.origin).replace(/\/$/, "");
const whiteboardCandidate = params.get("pissarra") || "https://marcjante.github.io/Pizarra-hoquei/";
const whiteboardUrl = /^https?:\/\//i.test(whiteboardCandidate) ? whiteboardCandidate : "";
const requestedPollSeconds = Number(params.get("poll"));
const adminPollMs = Number.isFinite(requestedPollSeconds) && requestedPollSeconds >= 5 && requestedPollSeconds <= 60
  ? requestedPollSeconds * 1000 : 8000;
const now = new Date();
const seasonStart = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
const season = params.get("season") || `${seasonStart}-${String(seasonStart + 1).slice(-2)}`;
const weekDate = new Date();
const weekDay = weekDate.getDay() || 7;
weekDate.setDate(weekDate.getDate() - weekDay + 1);
const currentWeekStart = weekDate.toISOString().slice(0, 10);

const state = { player: null, attendance: new Map(), progress: new Map(), checkins: new Map(), convocations: new Map(), teamConvocations: new Map() };
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
  if (!jugador) {
    document.querySelector("#loading").classList.add("hidden");
    document.querySelector("#access-disabled").classList.add("hidden");
    document.querySelector("#portal").classList.add("hidden");
    document.querySelector("#admin-portal").classList.remove("hidden");
    return;
  }
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
  document.querySelector("#admin-events").innerHTML = events.length ? events.map(event => `<article class="card deletable-card">
    <button class="delete-x" type="button" data-delete="/events/${event.id}" data-label="${escapeHtml(event.title)}" aria-label="Esborrar ${escapeHtml(event.title)}">×</button><p class="meta">${escapeHtml(dateFormat.format(new Date(event.starts_at)))}</p><h4>${escapeHtml(event.title)}</h4><p>${escapeHtml(event.location || "Sense ubicació")}</p>
  </article>`).join("") : empty("No hi ha esdeveniments.");
  document.querySelector("#event-video-form select[name=event_id]").innerHTML = events.map(event => `<option value="${event.id}">${escapeHtml(event.title)} · ${escapeHtml(dateFormat.format(new Date(event.starts_at)))}</option>`).join("");
}

function renderAdminGoals(goalsByPlayer, players) {
  const target = document.querySelector("#admin-goals");
  target.innerHTML = players.map(player => { const goals = goalsByPlayer.get(player.id) || []; return `<article class="card player-activity"><h3>${escapeHtml(player.name)}</h3>${goals.length ? `<ul class="task-list">${goals.map(goal => `<li><span>${escapeHtml(goal.title)}</span><span><strong class="task-status ${goal.done ? "done" : "pending"}">${goal.done ? "Fet" : "Pendent"}</strong><button class="delete-x inline-delete" type="button" data-delete="/goals/${goal.id}" data-label="${escapeHtml(goal.title)}" aria-label="Esborrar objectiu">×</button></span></li>`).join("")}</ul>` : `<p class="note">No té objectius assignats.</p>`}</article>`; }).join("");
}

function renderAdminEventVideos(videos, events) {
  const eventById = new Map(events.map(event => [event.id, event]));
  const target = document.querySelector("#admin-event-videos");
  target.innerHTML = videos.length ? videos.map(video => { const event = eventById.get(video.event_id); const source = /^https?:\/\//i.test(video.filename) ? video.filename : `/uploads/${encodeURIComponent(video.filename)}`; return `<article class="card deletable-card"><button class="delete-x" type="button" data-delete="/event-videos/${video.id}" data-label="el vídeo" aria-label="Esborrar vídeo">×</button><p class="meta">${event ? escapeHtml(dateFormat.format(new Date(event.starts_at))) : "Dia no disponible"} · ${event ? escapeHtml(event.title) : "Partit o entrenament"}</p><a class="action primary" href="${escapeHtml(source)}" target="_blank" rel="noopener">Veure vídeo</a>${video.comment ? `<p>${escapeHtml(video.comment)}</p>` : ""}</article>`; }).join("") : empty("Encara no hi ha vídeos guardats.");
}

function renderAdminActivity(items, players, assignmentsByPlayer, exercises, attendanceSummary, progressByPlayer) {
  const latest = new Map();
  items.filter(item => item.kind === "checkin").forEach(item => latest.set(`${item.player}:${item.label}`, item));
  const exerciseById = new Map(exercises.map(exercise => [exercise.id, exercise]));
  const attendanceByPlayer = new Map(attendanceSummary.map(row => [row.player_id, row]));
  document.querySelector("#admin-activity").innerHTML = players.map(player => {
    const assignments = assignmentsByPlayer.get(player.id) || [];
    const tasks = assignments.map(assignment => {
      const exercise = exerciseById.get(assignment.exercise_id);
      const checkin = latest.get(`${player.name}:${exercise?.title}`);
      const status = checkin ? (checkin.value ? "Fet" : "No fet") : "Pendent";
      return `<li><span>${escapeHtml(exercise?.title || "Exercici")}</span><strong class="task-status ${status === "Fet" ? "done" : status === "No fet" ? "missed" : "pending"}">${status}</strong></li>`;
    }).join("");
    const attendance = items.filter(item => item.kind === "attendance" && item.player === player.name).map(item => `<li><span>${escapeHtml(item.label)}</span><strong class="task-status ${item.value ? "done" : "missed"}">${item.value ? "Sí" : "No"}</strong></li>`).join("");
    const summary = attendanceByPlayer.get(player.id);
    const percentage = summary?.percentage == null ? "Sense dades" : `${summary.percentage}%`;
    const progress = progressByPlayer.get(player.id) || [];
    const latestWeek = progress.reduce((latest, row) => !latest || `${row.iso_year}-${row.iso_week}` > `${latest.iso_year}-${latest.iso_week}` ? row : latest, null);
    const weekRows = latestWeek ? progress.filter(row => row.iso_year === latestWeek.iso_year && row.iso_week === latestWeek.iso_week) : [];
    const exercisePercent = assignments.length ? Math.round(weekRows.reduce((sum, row) => sum + row.repetitions, 0) * 100 / (assignments.length * 3)) : null;
    return `<article class="card player-activity"><h3>${escapeHtml(player.name)}</h3><p class="meta">Assistència a entrenaments i partits</p>${attendance ? `<ul class="task-list">${attendance}</ul>` : `<p class="note">Encara no ha confirmat cap dia.</p>`}<p class="attendance-percent">Assistència total <strong>${percentage}</strong>${summary?.total ? ` <span>(${summary.attending}/${summary.total})</span>` : ""}</p><details class="activity-exercises"><summary>Exercicis i estiraments${assignments.length ? ` (${assignments.length})` : ""}</summary><p class="exercise-percent">Aquesta setmana: <strong>${exercisePercent == null ? "Sense dades" : `${exercisePercent}%`}</strong></p>${tasks ? `<ul class="task-list">${tasks}</ul>` : `<p class="note">No té exercicis assignats.</p>`}</details></article>`;
  }).join("") || empty("Encara no hi ha jugadors.");
}

function renderEventAttendanceSummary(rows) {
  document.querySelector("#event-attendance-summary").innerHTML = rows.length ? rows.sort((a, b) => new Date(a.starts_at) - new Date(b.starts_at)).map(row => `<div class="attendance-event"><span>${escapeHtml(dateFormat.format(new Date(row.starts_at)))} · ${escapeHtml(row.title)}</span><strong>${row.attending}</strong><small> disponibles de ${row.total} confirmats</small></div>`).join("") : "";
}

function renderAdminExercises(exercises, players) {
  document.querySelector("#admin-exercises").innerHTML = exercises.length ? exercises.map(exercise => `<article class="card deletable-card">
    <button class="delete-x" type="button" data-delete="/exercises/${exercise.id}" data-label="${escapeHtml(exercise.title)}" aria-label="Esborrar ${escapeHtml(exercise.title)}">×</button><p class="meta">${exercise.video_filename ? "Vídeo disponible" : "Sense vídeo"}</p>
    <h4>${escapeHtml(exercise.title)}</h4><p>${escapeHtml(exercise.description || "")}</p>
  </article>`).join("") : empty("Encara no hi ha exercicis al catàleg.");
  const exerciseOptions = exercises.map(exercise => `<option value="${exercise.id}">${escapeHtml(exercise.title)}</option>`).join("");
  document.querySelector("#assignment-form select[name=exercise_id]").innerHTML = exerciseOptions;
  document.querySelector("#video-form select[name=exercise_id]").innerHTML = exerciseOptions;
  document.querySelector("#assignment-form select[name=player_id]").innerHTML = players.map(player => `<option value="${player.id}">${escapeHtml(player.name)}</option>`).join("");
}

async function renderAdminCompetition(players, events) {
  const matches = events.filter(event => event.event_type === "match");
  const matchOptions = matches.map(event => `<option value="${event.id}">${escapeHtml(event.title)} · ${escapeHtml(dateFormat.format(new Date(event.starts_at)))}</option>`).join("");
  const playerOptions = players.map(player => `<option value="${player.id}">${escapeHtml(player.name)}</option>`).join("");
  ["#convocation-form", "#team-convocation-form", "#mvp-form"].forEach(selector => {
    document.querySelector(`${selector} select[name=event_id]`).innerHTML = matchOptions;
    const playerSelect = document.querySelector(`${selector} select[name=player_id], ${selector} select[name=player_ids]`);
    if (playerSelect) playerSelect.innerHTML = playerOptions;
  });
  document.querySelector("#reinforcement-form select[name=event_id]").innerHTML = matchOptions;
  const teamTarget = document.querySelector("#convocation-team");
  const convocations = await Promise.all(matches.map(async match => ({ match, rows: await api(`/convocations/event/${match.id}`) })));
  teamTarget.innerHTML = convocations.length ? convocations.map(({ match, rows }) => {
    const selected = rows.filter(row => row.selection_status === "selected");
    return `<article class="card"><p class="meta">${escapeHtml(dateFormat.format(new Date(match.starts_at)))}</p><h4>${escapeHtml(match.title)}</h4>${selected.length ? `<ul class="team-list">${selected.map(row => `<li>${escapeHtml(players.find(player => player.id === row.player_id)?.name || "Jugador")}</li>`).join("")}</ul>` : `<p class="note">Encara no hi ha jugadors convocats.</p>`}</article>`;
  }).join("") : empty("No hi ha partits per convocar.");
}

function renderAdminPlanning(players, exercises, routines) {
  const playerOptions = players.map(player => `<option value="${player.id}">${escapeHtml(player.name)}</option>`).join("");
  ["#follow-up-form", "#weekly-plan-form"].forEach(selector => {
    document.querySelector(`${selector} select[name=player_id]`).innerHTML = playerOptions;
  });
  const categories = [
    ["Força i casa", exercises.filter(exercise => !exercise.title.toLowerCase().startsWith("estirament") && !["Rotació toràcica", "Mobilitat de turmell", "Postura del nen"].includes(exercise.title))],
    ["Estiraments i mobilitat", exercises.filter(exercise => exercise.title.toLowerCase().startsWith("estirament") || ["Rotació toràcica", "Mobilitat de turmell", "Postura del nen"].includes(exercise.title))]
  ];
  document.querySelector("#weekly-exercise-options").innerHTML = categories.map(([label, rows]) => `<div class="exercise-group"><strong>${label}</strong>${rows.map(exercise => `<label class="exercise-option"><input type="checkbox" name="exercise_ids" value="${exercise.id}"><span>${escapeHtml(exercise.title)}</span></label>`).join("")}</div>`).join("");
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
  const [players, events, exercises, standings, activity, attendanceSummary, eventVideos, eventAttendanceSummary] = await Promise.all([api("/players"), api("/events"), api("/exercises"), api(`/standings?season=${encodeURIComponent(season)}`), api("/activity"), api("/activity/attendance-summary"), api("/event-videos"), api("/activity/event-attendance-summary")]);
  const goalsByPlayer = new Map(await Promise.all(players.map(async player => [player.id, await api(`/goals/player/${player.id}`)])));
  const playerData = await Promise.all(players.map(async player => [player.id, await api(`/exercises/player/${player.id}`), await api(`/exercise-progress/player/${player.id}`)]));
  const assignmentsByPlayer = new Map(playerData.map(([id, assignments]) => [id, assignments]));
  const progressByPlayer = new Map(playerData.map(([id, _assignments, progress]) => [id, progress]));
  const routineGroups = await Promise.all(players.map(player => api(`/routines/player/${player.id}`)));
  const routines = routineGroups.flatMap((items, index) => items.map(item => ({ ...item, player_name: players[index].name })));
  renderAdminPlayers(players); renderAdminEvents(events); renderAdminExercises(exercises, players); await renderAdminCompetition(players, events); renderAdminPlanning(players, exercises, routines);
  renderStandings(standings, "#admin-standings-body");
  renderAdminActivity(activity, players, assignmentsByPlayer, exercises, attendanceSummary, progressByPlayer);
  renderEventAttendanceSummary(eventAttendanceSummary);
  renderAdminEventVideos(eventVideos, events);
  renderAdminGoals(goalsByPlayer, players);
  } finally {
    adminLoadInFlight = false;
  }
}

function setupAdminForms() {
  document.querySelector("#admin-portal").addEventListener("click", async event => {
    const button = event.target.closest("[data-delete]");
    if (!button || !window.confirm(`Esborrar «${button.dataset.label}»?`)) return;
    button.disabled = true;
    try {
      await api(button.dataset.delete, { method: "DELETE" });
      await loadAdmin();
      adminToast("Element esborrat");
    } catch (_) {
      button.disabled = false;
      adminToast("No s'ha pogut esborrar (pot tenir dades vinculades)");
    }
  });
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
  document.querySelector("#event-video-form").addEventListener("submit", async event => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    try {
      await api("/event-videos", { method: "POST", body: fields });
      event.currentTarget.reset();
      adminToast("Vídeo publicat");
      try { await loadAdmin(); } catch (_) { /* el vídeo ya s'ha desat */ }
    } catch (_) { adminToast("No s'ha pogut pujar el vídeo"); }
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
      await loadAdmin();
      adminToast("Convocatòria desada");
    } catch (_) { showAccessDisabled(); }
  });
  document.querySelector("#team-convocation-form").addEventListener("submit", async event => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const eventId = fields.get("event_id");
    const playerIds = fields.getAll("player_ids");
    const note = fields.get("note") || null;
    try {
      await Promise.all(playerIds.map(playerId => api(`/convocations/${eventId}/${playerId}`, {
        method: "PUT", body: JSON.stringify({ selection_status: "selected", note })
      })));
      event.currentTarget.reset();
      await loadAdmin();
      adminToast("Equip convocat");
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
  document.querySelector("#weekly-plan-form").addEventListener("submit", async event => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const playerId = fields.get("player_id");
    const weekStart = fields.get("week_start");
    const exerciseIds = fields.getAll("exercise_ids");
    if (!exerciseIds.length) { adminToast("Tria almenys un exercici"); return; }
    const mandatory = fields.has("mandatory");
    try {
      await Promise.all(exerciseIds.map(exerciseId => api("/weekly-plan", { method: "POST", body: JSON.stringify({ player_id: Number(playerId), exercise_id: Number(exerciseId), week_start: weekStart, mandatory }) })));
      event.currentTarget.reset();
      adminToast("Pla setmanal enviat");
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

function setupAdminSections() {
  document.querySelectorAll("#admin-portal .admin-grid > section").forEach(section => {
    if (section.closest("details")) return;
    const heading = section.querySelector(":scope > .section-heading");
    if (!heading) return;
    const details = document.createElement("details");
    details.className = "admin-section";
    const summary = document.createElement("summary");
    summary.innerHTML = heading.innerHTML;
    details.appendChild(summary);
    [...section.children].filter(child => child !== heading).forEach(child => details.appendChild(child));
    section.replaceWith(details);
  });
}

async function startAdmin() {
  setupAdminSections();
  setupAdminForms();
  setupWhiteboard();
  try {
    await loadAdmin();
  } catch (_) {
    // El token ya ha sido validado; un fallo puntual de datos no debe bloquear
    // el acceso del entrenador al panel ni a sus formularios de edición.
    adminToast("No s'han pogut carregar totes les dades. Torna-ho a provar.");
  }
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

function renderEventVideos(videosByEvent, events) {
  const eventById = new Map(events.map(event => [event.id, event]));
  const rows = [...videosByEvent.entries()].flatMap(([eventId, videos]) => videos.map(video => ({ video, event: eventById.get(eventId) })));
  document.querySelector("#event-videos-list").innerHTML = rows.length ? rows.map(({ video, event }) => { const source = /^https?:\/\//i.test(video.filename) ? video.filename : `${API_BASE}/uploads/${encodeURIComponent(video.filename)}`; const label = event ? `${new Intl.DateTimeFormat("ca-ES", { weekday: "short", day: "numeric", month: "short" }).format(new Date(event.starts_at))} · ${event.event_type === "match" ? "Partit" : "Entrenament"}` : "Vídeo de l'equip"; return `<article class="card event-video-card"><div><p class="meta">${escapeHtml(label)}</p><h4>${escapeHtml(event?.title || "Vídeo de l'equip")}</h4></div><a class="action primary" href="${escapeHtml(source)}" target="_blank" rel="noopener noreferrer">Veure vídeo <span aria-hidden="true">↗</span></a>${video.comment ? `<p class="video-comment">${escapeHtml(video.comment)}</p>` : ""}</article>`; }).join("") : empty("Encara no hi ha vídeos publicats.");
}

function renderEvents(events) {
  const target = document.querySelector("#events-list");
  target.innerHTML = events.length ? events.map(event => {
    const attendance = state.attendance.get(event.id);
    const convocation = state.convocations.get(event.id);
    const team = state.teamConvocations.get(event.id) || [];
    const type = { training: "Entrenament", match: "Partit", meeting: "Reunió" }[event.event_type];
    const eventDate = new Date(event.starts_at);
    const dayLabel = new Intl.DateTimeFormat("ca-ES", { weekday: "long", day: "numeric", month: "long" }).format(eventDate);
    const timeLabel = new Intl.DateTimeFormat("ca-ES", { timeStyle: "short" }).format(eventDate);
    const callup = convocation ? { selected: "Convocat", reserve: "Reserva", not_selected: "No convocat" }[convocation.selection_status] : "";
    return `<article class="card">
      <div class="event-schedule"><span class="event-type">${escapeHtml(type)}</span><strong>${escapeHtml(dayLabel)}</strong><span>${escapeHtml(timeLabel)} · ${escapeHtml(event.location || "Ubicació per confirmar")}</span></div>
      <h3>${escapeHtml(event.title)}</h3>
      ${callup ? `<span class="callup">${escapeHtml(callup)}</span>` : ""}
      ${event.event_type === "match" ? `<div class="team-roster"><h4>Qui hi va (${team.length})</h4>${team.length ? `<ul class="team-list">${team.map(player => `<li>${escapeHtml(player.player_name)}</li>`).join("")}</ul>` : `<p class="note">Encara no hi ha equip seleccionat.</p>`}</div>` : ""}
      <div class="actions">
        <button class="action ${attendance?.attending === true ? "primary" : ""}" data-attendance="${event.id}" data-value="true">Hi aniré</button>
        <button class="action ${attendance?.attending === false ? "primary" : ""}" data-attendance="${event.id}" data-value="false">No hi podré anar</button>
      </div>
      <div class="attendance-reason ${attendance?.attending === false ? "" : "hidden"}" data-reason-panel="${event.id}">
        <label>Per què no podràs venir?<textarea data-reason-input maxlength="500" placeholder="Escriu el motiu" required>${escapeHtml(attendance?.absence_reason || "")}</textarea></label>
        <button class="action" data-attendance-save="${event.id}">Desar motiu</button>
      </div>
    </article>`;
  }).join("") : empty("No hi ha esdeveniments programats.");

  target.querySelectorAll("[data-attendance]").forEach(button => button.addEventListener("click", async () => {
    if (button.dataset.value === "false") {
      const panel = target.querySelector(`[data-reason-panel="${button.dataset.attendance}"]`);
      panel.classList.remove("hidden");
      panel.querySelector("textarea")?.focus();
      return;
    }
    try {
      const saved = await api(`/attendance/${button.dataset.attendance}/${state.player.id}`, {
        method: "PATCH", body: JSON.stringify({ attending: true })
      });
      state.attendance.set(saved.event_id, saved);
      renderEvents(events);
      showToast("Assistència desada");
    } catch (_) { showAccessDisabled(); }
  }));
  target.querySelectorAll("[data-attendance-save]").forEach(button => button.addEventListener("click", async () => {
    const panel = target.querySelector(`[data-reason-panel="${button.dataset.attendanceSave}"]`);
    const reason = panel.querySelector("textarea")?.value.trim() || "";
    if (!reason) { showToast("Escriu el motiu abans de desar"); return; }
    try {
      const saved = await api(`/attendance/${button.dataset.attendanceSave}/${state.player.id}`, {
        method: "PATCH", body: JSON.stringify({ attending: false, absence_reason: reason })
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

function renderHomeActivities(assignments, checkins, exercises) {
  const target = document.querySelector("#home-activities");
  target.innerHTML = assignments.length ? assignments.map(assignment => {
    const checkin = state.checkins.get(assignment.exercise_id);
    const exercise = exercises.find(item => item.id === assignment.exercise_id);
    return `<article class="card home-activity"><div><p class="meta">${assignment.mandatory ? "Obligatori · " : ""}Aquesta setmana</p><h4>${escapeHtml(exercise?.title || "Exercici")}</h4><p>${escapeHtml(exercise?.description || "")}</p></div><div class="actions"><button class="action ${checkin?.completed === true ? "primary" : ""}" data-checkin="${assignment.exercise_id}" data-completed="true">Fet</button><button class="action ${checkin?.completed === false ? "primary" : ""}" data-checkin="${assignment.exercise_id}" data-completed="false">No fet</button></div></article>`;
  }).join("") : empty("No tens treball a casa assignat.");
  target.querySelectorAll("[data-checkin]").forEach(button => button.addEventListener("click", async () => {
    try {
      const saved = await api(`/exercise-checkins/${state.player.id}/${button.dataset.checkin}`, { method: "PATCH", body: JSON.stringify({ completed: button.dataset.completed === "true" }) });
      state.checkins.set(saved.exercise_id, saved);
      renderHomeActivities(assignments, checkins, exercises);
      showToast("Activitat actualitzada");
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

function renderProgress(stats, followUp, mvp) {
  const totals = stats.reduce((sum, row) => ({ games: sum.games + row.games, goals: sum.goals + row.goals, assists: sum.assists + row.assists }), { games: 0, goals: 0, assists: 0 });
  document.querySelector("#metrics").innerHTML = [
    [totals.games, "Partits"], [totals.goals, "Gols"], [totals.assists, "Assistències"], [mvp.length, "MVP"]
  ].map(([value, label]) => `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`).join("");
  document.querySelector("#follow-up-list").innerHTML = followUp.length ? followUp.map(item => `<article class="card"><p class="meta">${escapeHtml(item.observed_on)} · ${escapeHtml(item.category)}</p><p>${escapeHtml(item.note)}</p></article>`).join("") : empty("Encara no hi ha observacions compartides.");
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
    const [events, attendance, goals, assignments, progress, routines, stats, followUp, mvp, convocations, standings, checkins, weeklyPlan] = await Promise.all([
      api("/events"), api(`/attendance/${id}`), api(`/goals/player/${id}`),
      api(`/exercises/player/${id}`), api(`/exercise-progress/player/${id}`),
      api(`/routines/player/${id}`), api(`/player-stats/player/${id}`),
      api(`/seguiment/player/${id}`), api(`/mvp/player/${id}`),
      api(`/convocations/player/${id}`), api(`/standings?season=${encodeURIComponent(season)}`), api(`/exercise-checkins/player/${id}`), api(`/weekly-plan/player/${id}?week_start=${currentWeekStart}`)
    ]);
    attendance.forEach(item => state.attendance.set(item.event_id, item));
    progress.forEach(item => state.progress.set(item.assignment_id, item));
    convocations.forEach(item => state.convocations.set(item.event_id, item));
    checkins.forEach(item => state.checkins.set(item.exercise_id, item));
    const matches = events.filter(event => event.event_type === "match");
    const teamLists = await Promise.all(matches.map(event => api(`/convocations/event/${event.id}/team`)));
    const eventVideos = await Promise.all(events.filter(event => event.event_type !== "meeting").map(async event => [event.id, await api(`/event-videos/event/${event.id}`)]));
    const videosByEvent = new Map(eventVideos);
    matches.forEach((event, index) => state.teamConvocations.set(event.id, teamLists[index]));
    document.querySelector("#welcome").textContent = `Hola, ${state.player.name}`;
    const planned = weeklyPlan.length ? weeklyPlan : assignments.map(item => ({ ...item, mandatory: false }));
    const activityExercises = await Promise.all(planned.map(item => api(`/exercises/${item.exercise_id}`)));
    renderEvents(events); renderEventVideos(videosByEvent, events); renderHomeActivities(planned, checkins, activityExercises); renderGoals(goals); await renderTraining(assignments, routines);
    renderProgress(stats, followUp, mvp);
    document.querySelector("#season-label").textContent = `Temporada ${season}`;
    renderStandings(standings);
    setupTabs();
    document.querySelector("#loading").classList.add("hidden");
    document.querySelector("#portal").classList.remove("hidden");
  } catch (_) {
    // El enlace de entrenador ya lleva un token; no ocultamos el panel por
    // un error puntual de inicialización de una sección secundaria.
    if (token && !jugador) {
      document.querySelector("#loading").classList.add("hidden");
      document.querySelector("#access-disabled").classList.add("hidden");
      document.querySelector("#admin-portal").classList.remove("hidden");
      adminToast("Panell obert. Algunes dades es poden carregar en uns segons.");
      return;
    }
    showAccessDisabled();
  }
}

start();
