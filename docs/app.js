"use strict";
/* Router hash: "#/" = strona główna, "#/YYYY-MM-DD" = widok dnia. */

const $view = document.getElementById("view");

/* ---------- motyw ---------- */
const themeBtn = document.getElementById("themeToggle");
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("theme", t);
}
applyTheme(localStorage.getItem("theme") ||
  (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
themeBtn.onclick = () =>
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");

/* ---------- pomocnicze ---------- */
const esc = s => String(s ?? "").replace(/[&<>"]/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

async function fetchJSON(url, retries = 2) {
  for (let i = 0; ; i++) {
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(r.status);
      return await r.json();
    } catch (e) {
      if (i >= retries) throw e;
      await new Promise(res => setTimeout(res, 800 * (i + 1)));
    }
  }
}

function daysUntil(termin) {
  if (!termin) return null;
  const t = new Date(termin + "T00:00:00");
  if (isNaN(t)) return null;
  return Math.ceil((t - Date.now()) / 864e5);
}

function badge(termin) {
  const d = daysUntil(termin);
  if (d === null) return `<span class="badge gray">termin nieznany</span>`;
  if (d < 0) return `<span class="badge gray">zakończony</span>`;
  if (d <= 7) return `<span class="badge red">termin: ${termin} (${d} dni)</span>`;
  if (d <= 14) return `<span class="badge yellow">termin: ${termin} (${d} dni)</span>`;
  return `<span class="badge green">termin: ${termin} (${d} dni)</span>`;
}

function cardHTML(o) {
  return `<article class="card">
    <h3>${esc(o.podmiot) || "<i>(nieokreślony podmiot)</i>"}</h3>
    <div class="meta">${badge(o.termin_skladania_ofert)}
      ${o.miejscowosc ? `<span class="badge place">📍 ${esc(o.miejscowosc)}</span>` : ""}
      ${o.stanowisko ? `<span class="badge gray">${esc(o.stanowisko)}</span>` : ""}
    </div>
    ${o.wymagania ? `<p class="req"><b>Wymagania:</b> ${esc(o.wymagania)}</p>` : ""}
    <p class="sum">${esc(o.podsumowanie)}</p>
    <a class="src" href="${esc(o.url)}" target="_blank" rel="noopener">źródło →</a>
  </article>`;
}

function skeletons(n) { return Array(n).fill('<div class="skeleton"></div>').join(""); }

function filtered(offers, q, onlyActive) {
  const term = q.trim().toLowerCase();
  return offers.filter(o => {
    if (onlyActive && daysUntil(o.termin_skladania_ofert) !== null
        && daysUntil(o.termin_skladania_ofert) < 0) return false;
    if (!term) return true;
    return [o.podmiot, o.miejscowosc, o.stanowisko, o.podsumowanie, o.url]
      .some(v => String(v ?? "").toLowerCase().includes(term));
  });
}

function sortOffers(list, mode) {
  const byTerm = (a, b) => (b.termin_skladania_ofert || "").localeCompare(a.termin_skladania_ofert || "");
  const byDays = (a, b) => (daysUntil(a.termin_skladania_ofert) ?? 9e9) - (daysUntil(b.termin_skladania_ofert) ?? 9e9);
  if (mode === "termin-rosnaco") return [...list].sort(byDays);
  if (mode === "termin-malejaco") return [...list].sort(byTerm);
  if (mode === "najnowsze") return [...list].sort((a, b) => (b.znaleziono_dnia || "").localeCompare(a.znaleziono_dnia || ""));
  return list;
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return isNaN(d) ? iso : d.toLocaleDateString("pl-PL",
    { weekday: "short", day: "numeric", month: "long", year: "numeric" });
}

function wireToolbar(offers) {
  const q = document.getElementById("q");
  const sort = document.getElementById("sort");
  const active = document.getElementById("active");
  const render = () => {
    const list = sortOffers(filtered(offers, q.value, active.classList.contains("on")), sort.value);
    document.getElementById("cards").innerHTML =
      list.length ? list.map(cardHTML).join("")
      : `<div class="empty" style="grid-column:1/-1">Brak ofert spełniających kryteria.</div>`;
  };
  q.oninput = render; sort.onchange = render;
  active.onclick = () => { active.classList.toggle("on"); render(); };
  render();
}

/* ---------- widok dnia (#/YYYY-MM-DD) ---------- */
async function viewDay(dateStr) {
  $view.innerHTML = skeletons(3);
  let payload;
  try {
    payload = await fetchJSON(`data/${dateStr}.json`);
  } catch {
    $view.innerHTML = `<div class="empty">Nie znaleziono danych dla dnia ${esc(dateStr)}.
      <br><a href="#/">← wróć na stronę główną</a></div>`;
    return;
  }
  const { offers, stats } = payload;

  $view.innerHTML = `
    <div class="hero">
      <h1>Oferty z ${esc(fmtDate(dateStr))}</h1>
      <p>Znaleziono <b class="num">${offers.length}</b> ofert tego dnia.
         <a href="#/">← wszystkie dni</a></p>
      <div class="stats-row">
        <span class="stat">Wyniki surowe: <b>${stats.raw_results ?? "—"}</b></span>
        <span class="stat">Po filtrowaniu LLM: <b>${stats.after_filter ?? "—"}</b></span>
        <span class="stat">Dodane oferty: <b>${stats.offers_added ?? "—"}</b></span>
      </div>
    </div>
    <div class="toolbar">
      <input id="q" type="search" placeholder="Szukaj: podmiot, miejscowość…">
      <select id="sort">
        <option value="termin-malejaco">Termin: najdalszy</option>
        <option value="termin-rosnaco">Termin: najbliższy</option>
        <option value="najnowsze">Data znalezienia</option>
      </select>
      <button id="active" class="chip on">tylko aktywne</button>
    </div>
    <div class="cards" id="cards"></div>
    <nav class="daynav" id="daynav"></nav>`;

  wireToolbar(offers);

  /* nawigacja sąsiednimi dniami */
  const idx = await fetchJSON("data/index.json");
  const dates = idx.map(d => d.date).sort();
  const i = dates.indexOf(dateStr);
  const link = (d, txt) => `<a href="#/${d || ""}" class="${d ? "" : "invisible"}">${txt}</a>`;
  document.getElementById("daynav").innerHTML =
    link(dates[i - 1], `← ${fmtDate(dates[i - 1]) || ""}`) +
    link(dates[i + 1], `${fmtDate(dates[i + 1]) || ""} →`);
}

/* ---------- strona główna (#/) ---------- */
async function viewHome() {
  $view.innerHTML = skeletons(3);
  let index, all;
  try {
    [index, all] = await Promise.all([fetchJSON("data/index.json"), fetchJSON("data/all.json")]);
  } catch {
    $view.innerHTML = `<div class="empty">Brak danych. Workflow runuje się codziennie o 07:00 —
      wróć później.</div>`;
    return;
  }
  const active = all.filter(o => (daysUntil(o.termin_skladania_ofert) ?? -1) >= 0);
  const urgent = active
    .sort((a, b) => (daysUntil(a.termin_skladania_ofert) ?? 9e9) - (daysUntil(b.termin_skladania_ofert) ?? 9e9))
    .slice(0, 3);

  $view.innerHTML = `
    <div class="hero">
      <h1>Otwarte nabory na członków rad nadzorczych</h1>
      <p><span class="num">${active.length}</span> aktywnych naborów łącznie ·
         ostatnia aktualizacja: <b class="num">${index[0] ? fmtDate(index[0].date) : "—"}</b>
         (workflow runuje codziennie o 07:00)</p>
    </div>
    ${urgent.length ? `<h2 class="section-title">Najbliżej terminu</h2>
      <div class="cards">${urgent.map(cardHTML).join("")}</div>` : ""}
    <h2 class="section-title">Wyniki według dni</h2>
    <p style="color:var(--muted);margin-top:0">Każdy dzień ma osobny link — kliknij kafel.</p>
    <div class="days-grid">
      ${index.map((d, i) => `
        <a class="day-card ${i === 0 ? "latest" : ""}" href="#/${d.date}">
          <div class="d">${fmtDate(d.date)}</div>
          <div class="c">${d.count} ofert · dodano ${d.stats.offers_added}</div>
        </a>`).join("")}
    </div>
    <h2 class="section-title">Wszystkie oferty (pełna historia)</h2>
    <div class="toolbar">
      <input id="q" type="search" placeholder="Szukaj we wszystkich dniach…">
      <select id="sort">
        <option value="najnowsze">Data znalezienia: najnowsze</option>
        <option value="termin-rosnaco">Termin: najbliższy</option>
        <option value="termin-malejaco">Termin: najdalszy</option>
      </select>
      <button id="active" class="chip on">tylko aktywne</button>
    </div>
    <div class="cards" id="cards"></div>`;

  wireToolbar(all);
}

/* ---------- router ---------- */
function route() {
  const m = location.hash.match(/^#\/(\d{4}-\d{2}-\d{2})$/);
  m ? viewDay(m[1]) : viewHome();
}
addEventListener("hashchange", route);
route();


