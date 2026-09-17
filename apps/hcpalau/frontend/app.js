"use strict";

const params = new URLSearchParams(window.location.search);
const token = params.get("token") || "";
const jugador = params.get("jugador") || "";
const API_BASE = (params.get("api") || window.location.origin).replace(/\/$/, "");

const state = { player: null, attendance: new Map(), progress: new Map() };
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
  document.querySelector("#access-disabled").classList.remove("hidden");
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
    const type = { training: "Entrenament", match: "Partit", meeting: "Reunió" }[event.event_type];
    return `<article class="card">
      <p class="meta">${escapeHtml(type)} · ${escapeHtml(dateFormat.format(new Date(event.starts_at)))}</p>
      <h3>${escapeHtml(event.title)}</h3>
      <p>${escapeHtml(event.location || "Ubicació per confirmar")}</p>
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
  if (!token || !jugador) return showAccessDisabled();
  try {
    const session = await api(`/auth/session?jugador=${encodeURIComponent(jugador)}`);
    if (session.role !== "player" || !session.player) return showAccessDisabled();
    state.player = session.player;
    const id = state.player.id;
    const [events, attendance, goals, assignments, progress, routines, stats, followUp, exams, mvp] = await Promise.all([
      api("/events"), api(`/attendance/${id}`), api(`/goals/player/${id}`),
      api(`/exercises/player/${id}`), api(`/exercise-progress/player/${id}`),
      api(`/routines/player/${id}`), api(`/player-stats/player/${id}`),
      api(`/seguiment/player/${id}`), api(`/exam-periods/player/${id}`), api(`/mvp/player/${id}`)
    ]);
    attendance.forEach(item => state.attendance.set(item.event_id, item));
    progress.forEach(item => state.progress.set(item.assignment_id, item));
    document.querySelector("#welcome").textContent = `Hola, ${state.player.name}`;
    renderEvents(events); renderGoals(goals); await renderTraining(assignments, routines);
    renderProgress(stats, followUp, exams, mvp);
    setupTabs();
    document.querySelector("#loading").classList.add("hidden");
    document.querySelector("#portal").classList.remove("hidden");
  } catch (_) { showAccessDisabled(); }
}

start();
