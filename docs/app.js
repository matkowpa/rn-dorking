"use strict";
/* Router hash: "#/" = strona główna, "#/YYYY-MM-DD" = widok dnia.
   Stara funkcjonalność (hero, statystyki, kafle dni, toolbar, pełne karty)
   w nowym stylu Slate/Violet (front-end.txt). Dane: docs/data z build_docs.py. */

const $view = document.getElementById("view");
const $count = document.getElementById("countBadge");

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

function cardHTML(o) {
  return `<article class="card">
    <h3>${esc(o.podmiot) || "<i>(nieokreślony podmiot)</i>"}</h3>
    <div class="meta">${badge(o.termin_skladania_ofert)}
      ${o.miejscowosc ? `<span class="badge place">📍 ${esc(o.miejscowosc)}</span>` : ""}
      ${o.data_publikacji ? `<span class="badge gray">📅 ${fmtDate(o.data_publikacji)}</span>` : ""}
      ${o.zrodlo ? `<span class="badge gray">${esc(o.zrodlo)}</span>` : ""}
      ${o.stanowisko ? `<span class="badge gray">${esc(o.stanowisko)}</span>` : ""}
    </div>
    ${o.wymagania ? `<p class="req"><b>Wymagania:</b> ${esc(o.wymagania)}</p>` : ""}
    <p class="sum">${esc(o.podsumowanie)}</p>
    <a class="src" href="${esc(o.url)}" target="_blank" rel="noopener">źródło →</a>
  </article>`;
}

function skeletons(n) {
  return Array(n).fill('<div class="skeleton"></div>').join("");
}

function filtered(offers, q, onlyActive) {
  const term = q.trim().toLowerCase();
  return offers.filter(o => {
    const d = daysUntil(o.termin_skladania_ofert);
    if (onlyActive && d !== null && d < 0) return false;
    if (!term) return true;
    return [o.podmiot, o.miejscowosc, o.stanowisko, o.podsumowanie, o.url, o.zrodlo]
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
const toolbarState = { q: "", sort: "najnowsze", onlyActive: false };

function wireToolbar(rerender) {
  const inp = document.getElementById("search");
  const sel = document.getElementById("sort");
  const chip = document.getElementById("chip-active");
  if (!inp) return;
  inp.addEventListener("input", () => { toolbarState.q = inp.value; rerender(); });
  sel.addEventListener("change", () => { toolbarState.sort = sel.value; rerender(); });
  chip.addEventListener("click", () => {
    toolbarState.onlyActive = !toolbarState.onlyActive;
    chip.classList.toggle("on", toolbarState.onlyActive);
    rerender();
  });
}

/* ---------- widok główny ---------- */
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

  const active = all.filter(o => (daysUntil(o.termin_skladania_ofert) ?? -1) >= 0);
  $count.textContent = active.length;

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
        <span class="stat-side-item">Ostatni run: <b>${idx.length ? fmtDate(idx[0].date) : "—"}</b></span>
      </div>
    </section>
    <section id="closest"></section>
    <h2 class="section-title">Wyniki według dni</h2>
    <div class="days-grid">
      ${idx.map((d, i) => `<a class="day-card${i === 0 ? " latest" : ""}" href="#/${d.date}">
        <div class="d">${fmtDate(d.date)}</div>
        <div class="c">${d.count} ofert · +${d.stats.offers_added} nowych</div>
      </a>`).join("")}
    </div>
    <h2 class="section-title">Wszystkie oferty</h2>
    <div class="toolbar">
      <input id="search" type="search" placeholder="Szukaj: podmiot, miejscowość, treść…">
      <select id="sort">
        <option value="najnowsze">najnowsze znalezione</option>
        <option value="termin-rosnaco">termin: najbliższy</option>
        <option value="termin-malejaco">termin: najdalszy</option>
      </select>
      <button id="chip-active" class="chip">tylko aktywne</button>
    </div>
    <div id="offers" class="cards"></div>`;

  const rerender = () => {
    const list = sortOffers(filtered(all, toolbarState.q, toolbarState.onlyActive), toolbarState.sort);
    document.getElementById("offers").innerHTML = list.length
      ? list.map(cardHTML).join("")
      : `<p class="empty">Brak ofert spełniających kryteria.</p>`;
  };

  wireToolbar(rerender);
  rerender();

  const near = sortOffers(active.filter(o => o.termin_skladania_ofert), "termin-rosnaco").slice(0, 3);
  if (near.length) {
    document.getElementById("closest").outerHTML =
      `<h2 class="section-title">Najbliżej terminu</h2><div class="cards">${near.map(cardHTML).join("")}</div>`;
  } else {
    document.getElementById("closest").remove();
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
    </p>
    <div class="cards">${offers.map(cardHTML).join("") || '<p class="empty">Brak ofert tego dnia.</p>'}</div>
    <nav class="daynav">
      ${prevDate ? `<a href="#/${prevDate}">← ${fmtDate(prevDate)}</a>` : `<a class="invisible" href="#/">←</a>`}
      <a href="#/">← Wszystkie oferty</a>
      ${nextDate ? `<a href="#/${nextDate}">${fmtDate(nextDate)} →</a>` : `<a class="invisible" href="#/">→</a>`}
    </nav>`;
}

/* ---------- router ---------- */
async function router() {
  const h = location.hash.replace(/^#\/?/, "");
  if (/^\d{4}-\d{2}-\d{2}$/.test(h)) {
    let idx = [];
    try { idx = await fetchJSON("data/index.json"); } catch (e) { /* nawigacja bez indeksu */ }
    viewDay(h, idx);
  } else {
    viewHome();
  }
}
window.addEventListener("hashchange", router);
router();