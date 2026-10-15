"use strict";
/* Router hash: "#/" = strona główna, "#/YYYY-MM-DD" = widok dnia.
   Stara funkcjonalność (hero, statystyki, kafle dni, toolbar, pełne karty)
   w nowym stylu Slate/Violet (front-end.txt). Dane: docs/data z build_docs.py.
   Etap 1 wg front-end.txt: Ulubione (localStorage), pill-filtry
   (Wszystkie/Nowe/W toku/Zapisane), Drawer szczegółów, statusy NOWE/PILNE. */

const $view = document.getElementById("view");
const $count = document.getElementById("countBadge");

/* ---------- pomocnicze ---------- */
const esc = s => String(s ?? "").replace(/[&<>"]+/g, c => [...c].map(ch => "&#" + ch.codePointAt(0) + ";").join(""));

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
  if (d <= 7) return `<span class="badge red">termin: ${esc(termin)} (${d} dni)</span>`;
  if (d <= 14) return `<span class="badge yellow">termin: ${esc(termin)} (${d} dni)</span>`;
  return `<span class="badge green">termin: ${esc(termin)} (${d} dni)</span>`;
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return isNaN(d) ? iso : d.toLocaleDateString("pl-PL",
    { day: "numeric", month: "short", year: "numeric" });
}

/* ---------- Ulubione / przeczytane (localStorage, spec §1 §4) ---------- */
const FAV_KEY = "rn-favorites";
const SEEN_KEY = "rn-seen";

function loadSet(key) {
  try { return new Set(JSON.parse(localStorage.getItem(key) || "[]")); }
  catch { return new Set(); }
}
function saveSet(key, set) {
  try { localStorage.setItem(key, JSON.stringify([...set])); } catch { /* prywatny tryb */ }
}
const favs = () => loadSet(FAV_KEY);
function toggleFav(url) {
  const s = favs(); s.has(url) ? s.delete(url) : s.add(url); saveSet(FAV_KEY, s);
  return s.has(url);
}
const seenSet = () => loadSet(SEEN_KEY);
function markSeen(url) { const s = seenSet(); s.add(url); saveSet(SEEN_KEY, s); }

/* status wg spec §3: NOWE (bez terminu), PILNE (≤3 dni), W TOKU, zakończone */
function statusOf(o) {
  const d = daysUntil(o.termin_skladania_ofert);
  if (d === null) return { key: "new", label: "NOWE" };
  if (d < 0) return { key: "gone", label: "ZAKOŃCZONE" };
  if (d <= 3) return { key: "urgent", label: `PILNE · ${d} dni` };
  return { key: "open", label: "W TOKU" };
}

function cardHTML(o) {
  const st = statusOf(o);
  const isFav = favs().has(o.url);
  const seen = seenSet().has(o.url);
  return `<article class="card${seen ? " seen" : ""}" data-url="${esc(o.url)}">
    <button class="fav${isFav ? " on" : ""}" data-fav="${esc(o.url)}"
            title="${isFav ? "Usuń z ulubionych" : "Dodaj do ulubionych"}"
            aria-label="${isFav ? "Usuń z ulubionych" : "Dodaj do ulubionych"}">★</button>
    <span class="status st-${st.key}">${st.label}</span>
    <h3>${esc(o.podmiot) || "<i>(nieokreślony podmiot)</i>"}</h3>
    <div class="meta">${badge(o.termin_skladania_ofert)}
      ${o.miejscowosc ? `<span class="badge place">📍 ${esc(o.miejscowosc)}</span>` : ""}
      ${o.data_publikacji ? `<span class="badge gray">📅 ${fmtDate(o.data_publikacji)}</span>` : ""}
      ${o.zrodlo ? `<span class="badge gray">${esc(o.zrodlo)}</span>` : ""}
      ${o.stanowisko ? `<span class="badge gray">${esc(o.stanowisko)}</span>` : ""}
    </div>
    ${o.wymagania ? `<p class="req"><b>Wymagania:</b> ${esc(o.wymagania)}</p>` : ""}
    <p class="sum">${esc(o.podsumowanie)}</p>
    <div class="card-actions">
      <button class="more" data-more="${esc(o.url)}">Zobacz więcej ▸</button>
      <a class="src" href="${esc(o.url)}" target="_blank" rel="noopener">źródło →</a>
    </div>
  </article>`;
}

/* ---------- Drawer szczegółów (spec §4) ---------- */
function drawerHTML(o) {
  const st = statusOf(o);
  const isFav = favs().has(o.url);
  const d = daysUntil(o.termin_skladania_ofert);
  return `<div class="drawer-backdrop" data-close></div>
  <aside class="drawer" role="dialog" aria-label="Szczegóły ogłoszenia">
    <header class="drawer-head">
      <div>
        <span class="status st-${st.key}">${st.label}</span>
        <h2>${esc(o.podmiot) || "<i>(nieokreślony podmiot)</i>"}</h2>
      </div>
      <button class="drawer-close" data-close aria-label="Zamknij">✕</button>
    </header>
    <div class="drawer-body">
      <dl class="facts">
        ${o.stanowisko ? `<div><dt>Stanowisko</dt><dd>${esc(o.stanowisko)}</dd></div>` : ""}
        ${o.miejscowosc ? `<div><dt>Miejscowość</dt><dd>${esc(o.miejscowosc)}</dd></div>` : ""}
        ${o.data_publikacji ? `<div><dt>Publikacja</dt><dd>${fmtDate(o.data_publikacji)}</dd></div>` : ""}
        ${o.termin_skladania_ofert ? `<div><dt>Termin składania</dt><dd><b>${fmtDate(o.termin_skladania_ofert)}</b>${d !== null && d >= 0 ? ` <span class="mono">(${d} dni)</span>` : ""}</dd></div>` : ""}
        ${o.zrodlo ? `<div><dt>Źródło</dt><dd>${esc(o.zrodlo)}</dd></div>` : ""}
        <div><dt>Znaleziono</dt><dd>${fmtDate(o.znaleziono_dnia)}</dd></div>
      </dl>
      ${o.wymagania ? `<section class="dsec"><h4>Wymagania</h4><p>${esc(o.wymagania)}</p></section>` : ""}
      ${o.podsumowanie ? `<section class="dsec"><h4>Podsumowanie</h4><p>${esc(o.podsumowanie)}</p></section>` : ""}
      <div class="drawer-actions">
        <button class="fav wide${isFav ? " on" : ""}" data-fav="${esc(o.url)}">★ ${isFav ? "W ulubionych" : "Dodaj do ulubionych"}</button>
        <a class="src wide" href="${esc(o.url)}" target="_blank" rel="noopener">Otwórz ogłoszenie →</a>
      </div>
      <p class="drawer-hint">Pola uzupełnia LLM z treści ogłoszenia — pełna wersja zawsze w źródle.</p>
    </div>
  </aside>`;
}

function escHandler(e) { if (e.key === "Escape") closeDrawer(); }

function closeDrawer() {
  const w = document.getElementById("drawer-root");
  if (!w) return;
  w.classList.remove("open");
  document.body.style.overflow = "";
  setTimeout(() => w.remove(), 220);
  document.removeEventListener("keydown", escHandler);
}

function openDrawer(url) {
  const o = _allOffers.find(x => x.url === url);
  if (!o) return;
  markSeen(url);
  const w = document.getElementById("drawer-root");
  if (w) w.remove();
  const wrap = document.createElement("div");
  wrap.id = "drawer-root";
  wrap.innerHTML = drawerHTML(o);
  document.body.appendChild(wrap);
  document.body.style.overflow = "hidden";
  requestAnimationFrame(() => wrap.classList.add("open"));
  wrap.addEventListener("click", e => {
    if (e.target.closest("[data-close]") || e.target === wrap) { closeDrawer(); rerenderHome(); }
    if (e.target.closest("[data-fav]")) {
      const on = toggleFav(url);
      document.querySelectorAll(`[data-fav]`).forEach(b => {
        const isOn = b.dataset.fav === url ? on : favs().has(b.dataset.fav);
        b.classList.toggle("on", isOn);
      });
      rerenderHome();
    }
  });
  document.addEventListener("keydown", escHandler);
}

function skeletons(n) {
  return Array(n).fill('<div class="skeleton"></div>').join("");
}

/* ---------- filtrowanie wg spec §4: q + pills ---------- */
/* pills: all | new (NOWE+PILNE) | open (W TOKU) | fav (Zapisane) */
const toolbarState = { q: "", sort: "najnowsze", pill: "all" };

const PILLS = [
  ["all", "Wszystkie"],
  ["new", "Nowe"],
  ["open", "W toku"],
  ["fav", "★ Zapisane"],
];

function pillsHTML() {
  return PILLS.map(([key, label]) =>
    `<button type="button" class="pill${toolbarState.pill === key ? " on" : ""}" data-pill="${key}">${label}</button>`).join("");
}

function filtered(offers, state) {
  const term = state.q.trim().toLowerCase();
  return offers.filter(o => {
    const st = statusOf(o);
    if (state.pill === "new" && !(st.key === "new" || st.key === "urgent")) return false;
    if (state.pill === "open" && st.key !== "open") return false;
    if (state.pill === "fav" && !favs().has(o.url)) return false;
    if (!term) return true;
    return [o.podmiot, o.miejscowosc, o.stanowisko, o.podsumowanie, o.wymagania, o.url, o.zrodlo]
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

/* ---------- toolbar (strona główna) ---------- */
function wireToolbar(rerender) {
  const inp = document.getElementById("search");
  const sel = document.getElementById("sort");
  const pillsEl = document.getElementById("pills");
  if (!inp) return;
  inp.addEventListener("input", () => { toolbarState.q = inp.value; rerender(); });
  sel.addEventListener("change", () => { toolbarState.sort = sel.value; rerender(); });
  pillsEl.addEventListener("click", e => {
    const b = e.target.closest("[data-pill]");
    if (!b) return;
    toolbarState.pill = b.dataset.pill;
    pillsEl.querySelectorAll("[data-pill]").forEach(p => p.classList.toggle("on", p === b));
    rerender();
  });
}

/* ---------- widok główny ---------- */
let _allOffers = [];

function rerenderHome() {
  const cards = document.getElementById("offers");
  if (!cards || !_allOffers.length) return;
  const list = sortOffers(filtered(_allOffers, toolbarState), toolbarState.sort);
  cards.innerHTML = list.length
    ? list.map(cardHTML).join("")
    : `<p class="empty">Brak ofert spełniających kryteria.</p>`;
}

async function viewHome() {
  $view.innerHTML = skeletons(6);
  let idx, all;
  try {
    [idx, all] = await Promise.all([
      fetchJSON("data/index.json"),
      fetchJSON("data/all.json"),
    ]);
  } catch (e) {
    $view.innerHTML = `<div class="card"><p>Nie udało się pobrać danych. Spróbuj odświeżyć stronę.</p></div>`;
    return;
  }
  _allOffers = all;

  const active = all.filter(o => (daysUntil(o.termin_skladania_ofert) ?? -1) >= 0);
  $count.textContent = active.length;

  const favCount = favs().size;
  $view.innerHTML = `
    <section class="hero">
      <h1>Nabory do rad nadzorczych</h1>
      <p>Ogłoszenia o naborze kandydatów zbierane automatycznie z polskich BIP-ów i stron spółek.</p>
    </section>
    <section class="stats-banner">
      <div><span class="stat-big-num">${active.length}</span> <span class="stat-big-label">aktywnych naborów</span></div>
      <div class="stat-side">
        <span class="stat-side-item">Ofert łącznie: <b>${all.length}</b></span>
        <span class="stat-side-item">Dni monitoringu: <b>${idx.length}</b></span>
        <span class="stat-side-item">W ulubionych: <b>${favCount}</b></span>
        <span class="stat-side-item">Ostatni run: <b>${idx.length ? fmtDate(idx[0].date) : "—"}</b></span>
        <span class="stat-side-item"><a class="src" href="nabory.ics" title="Kalendarz aktywnych terminów (iCalendar)">📅 kalendarz (ICS)</a></span>
      </div>
    </section>
    <h2 class="section-title">Wszystkie oferty</h2>
    <div class="toolbar">
      <input id="search" type="search" placeholder="Szukaj: podmiot, miejscowość, treść…" value="${esc(toolbarState.q)}">
      <div class="pills" id="pills">${pillsHTML()}</div>
      <select id="sort">
        <option value="najnowsze">najnowsze znalezione</option>
        <option value="termin-rosnaco">termin: najbliższy</option>
        <option value="termin-malejaco">termin: najdalszy</option>
      </select>
    </div>
    <div id="offers" class="cards"></div>
    <section id="closest"></section>
    <h2 class="section-title">Wyniki według dni</h2>
    <div class="days-grid">
      ${idx.map((d, i) => `<a class="day-card${i === 0 ? " latest" : ""}" href="#/${d.date}">
        <div class="d">${fmtDate(d.date)}</div>
        <div class="c">${d.count} ofert · +${d.stats.offers_added} nowych</div>
      </a>`).join("")}
    </div>`;

  const sel = document.getElementById("sort");
  sel.value = toolbarState.sort;

  wireToolbar(rerenderHome);
  rerenderHome();

  const near = sortOffers(active.filter(o => o.termin_skladania_ofert), "termin-rosnaco").slice(0, 3);
  const closest = document.getElementById("closest");
  if (near.length) {
    closest.outerHTML =
      `<h2 class="section-title">Najbliżej terminu</h2><div class="cards" id="closest-cards">${near.map(cardHTML).join("")}</div>`;
  } else {
    closest.remove();
  }
}

/* ---------- widok dnia ---------- */
async function viewDay(date, idx) {
  $view.innerHTML = skeletons(3);
  let day;
  try {
    day = await fetchJSON(`data/${date}.json`);
  } catch (e) {
    $view.innerHTML = `<p class="empty">Brak danych dla dnia ${fmtDate(date)}.</p>
      <p style="text-align:center"><a class="src" href="#/">← Wszystkie oferty</a></p>`;
    return;
  }
  _allOffers = day.offers || [];
  const s = day.stats || {};
  const offers = day.offers || [];
  const pos = idx.findIndex(d => d.date === date);
  const prevDate = pos >= 0 && pos + 1 < idx.length ? idx[pos + 1].date : null;
  const nextDate = pos > 0 ? idx[pos - 1].date : null;

  $view.innerHTML = `
    <h2 class="section-title">Wyniki z dnia: ${fmtDate(date)}</h2>
    <p class="stat-side-item" style="margin:0 0 1rem">
      surowe wyniki: <b>${s.raw_results ?? "—"}</b> · źródła bezpośrednie: <b>${s.direct_results ?? 0}</b> ·
      po filtrze: <b>${s.after_filter ?? "—"}</b> ·
      dodano ofert: <b>${s.offers_added ?? "—"}</b> · łącznie tego dnia: <b>${offers.length}</b>
      ${s.offers_with_termin != null ? ` · z terminem: <b>${s.offers_with_termin}/${s.offers_added ?? 0}</b>` : ""}
      ${s.content_empty != null ? ` · bez treści: <b>${s.content_empty}</b>` : ""}
    </p>
    <div class="cards">${offers.length ? offers.map(cardHTML).join("") : '<p class="empty">Brak ofert tego dnia.</p>'}</div>
    <nav class="daynav">
      ${prevDate ? `<a href="#/${prevDate}">← ${fmtDate(prevDate)}</a>` : `<a class="invisible" href="#/">←</a>`}
      <a href="#/">← Wszystkie oferty</a>
      ${nextDate ? `<a href="#/${nextDate}">${fmtDate(nextDate)} →</a>` : `<a class="invisible" href="#/">→</a>`}
    </nav>`;
}

/* ---------- analityka (GoatCounter, bez cookies) ---------- */
/* Router jest hashowy, więc odsłony liczymy ręcznie (no_onload w index.html) —
   inaczej każde wejście zapisałoby się jako "/" i nie byłoby widać widoków dni.
   Licznik rusza dopiero po wpisaniu własnego kodu witryny w index.html. */
const gcEndpoint = document.querySelector("script[data-goatcounter]")?.dataset.goatcounter || "";
const gcOn = !gcEndpoint.includes("YOURCODE");

function gcCount(vars) {
  if (gcOn && window.goatcounter?.count) window.goatcounter.count(vars);
}

/* ---------- globalne kliknięcia: ulubione, drawer, źródło ---------- */
document.addEventListener("click", e => {
  const fav = e.target.closest("[data-fav]");
  if (fav) {
    e.preventDefault(); e.stopPropagation();
    const url = fav.dataset.fav;
    toggleFav(url);
    document.querySelectorAll(`[data-fav="${CSS.escape(url)}"]`)
      .forEach(b => b.classList.toggle("on", favs().has(url)));
    rerenderHome();
    return;
  }
  const more = e.target.closest("[data-more]");
  if (more) { e.preventDefault(); openDrawer(more.dataset.more); return; }
  const src = e.target.closest(".card a.src");
  if (src) gcCount({ path: "klik-zrodlo", title: src.closest(".card").querySelector("h3").textContent, event: true });
});

/* ---------- router ---------- */
async function router() {
  const h = location.hash.replace(/^#\/?/, "");
  if (/^\d{4}-\d{2}-\d{2}$/.test(h)) {
    gcCount({ path: `/${h}`, title: `Wyniki z dnia ${h}` });
    let idx = [];
    try { idx = await fetchJSON("data/index.json"); } catch (e) { /* nawigacja bez indeksu */ }
    viewDay(h, idx);
  } else {
    gcCount({ path: "/", title: "Strona główna" });
    viewHome();
  }
}
window.addEventListener("hashchange", () => { closeDrawer(); router(); });
router();
