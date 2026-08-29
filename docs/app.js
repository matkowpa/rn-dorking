"use strict";
/* Aggregator Ogłoszeń RN — feed "Clean Structured Cards" (front-end.txt).
   Router hash: "#/" = strona główna (feed + historia dni), "#/YYYY-MM-DD" = feed dnia. */

const $feed = document.getElementById("feedContainer");

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

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return isNaN(d) ? iso
    : d.toLocaleDateString("pl-PL", { day: "numeric", month: "short", year: "numeric" });
}

/* ---------- Ulubione (localStorage) ---------- */
let savedIds = JSON.parse(localStorage.getItem("saved_rn_ads") || "[]");
function persistSaved() {
  localStorage.setItem("saved_rn_ads", JSON.stringify(savedIds));
}

/* ---------- warstwa mapowania: oferta potoku -> view model feedu ---------- */
function urlId(url) {
  // Stabilne id z URL-a (djb2 → base36) — klucz Ulubionych między sesjami
  let h = 5381;
  for (const c of String(url || "")) h = ((h << 5) + h + c.charCodeAt(0)) | 0;
  return "rn-" + (h >>> 0).toString(36);
}

function splitRequirements(text) {
  // "wymagania" z potoku to jeden string — tniemy na punkty po ; lub ". "
  if (!text) return [];
  return String(text).split(/\s*[;.]\s+/)
    .map(s => s.trim()).filter(s => s.length > 8).slice(0, 8);
}

function toVM(o) {
  const d = daysUntil(o.termin_skladania_ofert);
  const foundDays = o.znaleziono_dnia
    ? Math.floor((Date.now() - new Date(o.znaleziono_dnia + "T00:00:00")) / 864e5) : 99;
  let status = "W TOKU";
  if (d !== null && d < 0) status = "done";
  else if (d !== null && d <= 3) status = "URGENT";
  else if (foundDays <= 2) status = "NEW";
  return {
    id: urlId(o.url),
    title: (o.stanowisko || "").trim() || "Członek rady nadzorczej",
    organization: o.podmiot || "(nieokreślony podmiot)",
    location: o.miejscowosc || "",
    deadlineDate: o.termin_skladania_ofert || "",
    foundDate: o.znaleziono_dnia || "",
    status,
    requirements: splitRequirements(o.wymagania),
    summary: o.podsumowanie || "",
    sourceUrl: o.url || "",
  };
}

/* ---------- statusy (design tokens z front-end.txt) ---------- */
const BADGE = {
  NEW:      { label: "Nowe",      cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
  URGENT:   { label: "Pilne",     cls: "bg-rose-500/10 text-rose-400 border-rose-500/20" },
  "W TOKU": { label: "W toku",    cls: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
  done:     { label: "Zakończone", cls: "bg-slate-500/10 text-slate-400 border-slate-500/20" },
};

/* stan widoku */
let currentList = [];      // view models bieżącego widoku (posortowane)
let currentFilter = "all";

function sortKey(item) {
  const d = daysUntil(item.deadlineDate);
  if (d === null) return 8500;    // termin nieznany — po aktywnych
  if (d < 0) return 9000 + (-d);  // zakończone — na końcu
  return d;                       // im bliżej terminu, tym wyżej
}

/* ---------- renderowanie feedu ---------- */
function skeletons(n) {
  return Array(n).fill(
    '<div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 h-40 animate-pulse"></div>').join("");
}

function deadlineHTML(item) {
  if (!item.deadlineDate) return `<span class="text-xs text-slate-500 font-mono">termin nieznany</span>`;
  const d = daysUntil(item.deadlineDate);
  const suffix = d !== null && d >= 0 ? ` (${d} dni)` : "";
  return `<span class="text-xs text-slate-500 font-mono">Do: ${esc(fmtDate(item.deadlineDate))}${suffix}</span>`;
}

function cardHTML(item) {
  const isSaved = savedIds.includes(item.id);
  const b = BADGE[item.status] || BADGE["W TOKU"];
  return `<article class="bg-slate-900 border border-slate-800 hover:border-slate-700/80 rounded-2xl p-5 transition space-y-4 shadow-lg">
    <div class="flex justify-between items-start gap-4">
      <div class="min-w-0">
        <div class="flex items-center gap-2 mb-1.5 flex-wrap">
          <span class="text-[10px] font-mono uppercase px-2 py-0.5 rounded border ${b.cls}">${b.label}</span>
          ${deadlineHTML(item)}
          ${item.location ? `<span class="text-xs text-slate-400">📍 ${esc(item.location)}</span>` : ""}
        </div>
        <h3 class="text-base font-bold text-white hover:text-violet-400 cursor-pointer transition"
            onclick="openDrawer('${item.id}')">${esc(item.title)}</h3>
        <p class="text-xs text-slate-400 mt-0.5">${esc(item.organization)}</p>
      </div>
      <button onclick="toggleSave('${item.id}')" title="Dodaj do ulubionych" aria-label="Dodaj do ulubionych"
              class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 transition shrink-0">
        ${isSaved ? "⭐" : "☆"}
      </button>
    </div>
    <p class="text-xs text-slate-400 line-clamp-2 leading-relaxed">${esc(item.summary)}</p>
    <div class="flex justify-between items-center pt-2 border-t border-slate-800/60 text-xs">
      <span class="text-slate-500 font-mono text-[11px]">Znaleziono: ${esc(fmtDate(item.foundDate)) || "—"}</span>
      <button onclick="openDrawer('${item.id}')"
              class="bg-slate-800 hover:bg-violet-600 text-slate-200 hover:text-white px-3.5 py-1.5 rounded-lg font-medium transition">
        Szczegóły ➔
      </button>
    </div>
  </article>`;
}

function renderFeed() {
  const query = document.getElementById("searchInput").value.trim().toLowerCase();
  const filtered = currentList.filter(item => {
    const hay = [item.title, item.organization, item.location, item.summary,
                 item.requirements.join(" "), item.sourceUrl].join(" ").toLowerCase();
    if (query && !hay.includes(query)) return false;
    if (currentFilter === "NEW") return item.status === "NEW";
    if (currentFilter === "URGENT") return item.status === "URGENT";
    if (currentFilter === "saved") return savedIds.includes(item.id);
    return true;
  });
  document.getElementById("countBadge").innerText = filtered.length;
  $feed.innerHTML = filtered.length
    ? filtered.map(cardHTML).join("")
    : `<div class="text-center py-12 text-slate-500 text-sm">Brak ogłoszeń spełniających kryteria.</div>`;
}

function setFeed(offers) {
  currentList = offers.map(toVM).sort((a, b) => sortKey(a) - sortKey(b));
  renderFeed();
}

/* ---------- filtry i Ulubione ---------- */
const BTN_IDLE = "filter-btn px-3 py-1.5 rounded-lg border border-slate-800 bg-slate-900 text-slate-400 hover:text-white transition";
const BTN_ACTIVE = "filter-btn px-3 py-1.5 rounded-lg border bg-violet-600 border-violet-500 text-white font-medium transition";

function setFilter(type) {
  currentFilter = type;
  document.querySelectorAll(".filter-btn").forEach(btn => { btn.className = BTN_IDLE; });
  const active = document.getElementById(`btn-${type}`);
  if (active) active.className = BTN_ACTIVE;
  renderFeed();
}

function toggleSave(id) {
  savedIds = savedIds.includes(id) ? savedIds.filter(i => i !== id) : [...savedIds, id];
  persistSaved();
  renderFeed();
}

/* ---------- drawer szczegółów ---------- */
function openDrawer(id) {
  const item = currentList.find(i => i.id === id);
  if (!item) return;
  const b = BADGE[item.status] || BADGE["W TOKU"];
  const st = document.getElementById("drawerStatus");
  st.textContent = b.label;
  st.className = `text-[10px] font-mono uppercase px-2 py-0.5 rounded border ${b.cls}`;
  document.getElementById("drawerTitle").innerText = item.title;
  document.getElementById("drawerOrg").innerText = item.organization;
  document.getElementById("drawerDeadline").innerText =
    item.deadlineDate ? fmtDate(item.deadlineDate) : "nieznany";
  document.getElementById("drawerLocation").innerText = item.location || "—";
  document.getElementById("drawerSummary").innerText = item.summary || "—";
  const reqSection = document.getElementById("drawerReqSection");
  reqSection.style.display = item.requirements.length ? "" : "none";
  document.getElementById("drawerRequirements").innerHTML =
    item.requirements.map(r => `<li>${esc(r)}</li>`).join("");
  document.getElementById("drawerSourceBtn").href = item.sourceUrl || "#";
  document.getElementById("drawer").classList.remove("hidden");
  document.body.classList.add("overflow-hidden");
}

function closeDrawer() {
  document.getElementById("drawer").classList.add("hidden");
  document.body.classList.remove("overflow-hidden");
}

/* ---------- widoki (router hash, hybryda) ---------- */
async function viewHome() {
  $feed.innerHTML = skeletons(4);
  let index, all;
  try {
    [index, all] = await Promise.all([fetchJSON("data/index.json"), fetchJSON("data/all.json")]);
  } catch {
    $feed.innerHTML = `<div class="text-center py-12 text-slate-500 text-sm">Brak danych.
      Workflow runuje dwa razy dziennie (07:00 i 19:00) — wróć później.</div>`;
    return;
  }
  setFeed(all);
  document.getElementById("viewTitle").style.display = "none";
  document.getElementById("daynav").style.display = "none";
  document.getElementById("historySection").style.display = "";
  document.getElementById("daysGrid").innerHTML = index.map((d, i) => `
    <a class="block bg-slate-900 border ${i === 0 ? "border-violet-500/60" : "border-slate-800"} hover:border-slate-600 rounded-xl p-3 transition"
       href="#/${d.date}">
      <div class="text-sm font-semibold text-slate-200 font-mono">${esc(fmtDate(d.date))}</div>
      <div class="text-xs text-slate-500 mt-1">${d.count} ofert · dodano ${d.stats?.offers_added ?? 0}</div>
    </a>`).join("");
}

async function viewDay(dateStr) {
  $feed.innerHTML = skeletons(3);
  let day, index;
  try {
    [day, index] = await Promise.all([
      fetchJSON(`data/${dateStr}.json`), fetchJSON("data/index.json")]);
  } catch {
    $feed.innerHTML = `<div class="text-center py-12 text-slate-500 text-sm">Brak danych dla dnia ${esc(dateStr)}.</div>`;
    return;
  }
  setFeed(day.offers || []);
  const title = document.getElementById("viewTitle");
  title.textContent = `Wyniki z dnia: ${fmtDate(dateStr)}`;
  title.style.display = "";
  document.getElementById("historySection").style.display = "none";
  const dates = index.map(d => d.date).sort();
  const i = dates.indexOf(dateStr);
  const link = (d, txt) =>
    `<a href="#/${d || ""}" class="${d ? "text-violet-400 hover:text-violet-300 font-mono text-xs" : "invisible"}">${esc(txt)}</a>`;
  const nav = document.getElementById("daynav");
  nav.innerHTML = link(dates[i - 1], `← ${fmtDate(dates[i - 1]) || ""}`) +
                  link(dates[i + 1], `${fmtDate(dates[i + 1]) || ""} →`);
  nav.style.display = "flex";
}

/* ---------- router + nasłuchiwacze ---------- */
function route() {
  const m = location.hash.match(/^#\/(\d{4}-\d{2}-\d{2})$/);
  m ? viewDay(m[1]) : viewHome();
}

document.getElementById("searchInput").addEventListener("input", renderFeed);
document.getElementById("drawer").addEventListener("click",
  e => { if (e.target.id === "drawer") closeDrawer(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
addEventListener("hashchange", route);
route();