"use strict";

const PAGE = 150;
const MARATHON_KM = 42.195;
const DISCIPLINES = ["trail", "road", "ultra", "sky", "other"];
const STATUS_LABEL = { open: "Registration open", closed: "Closed", upcoming: "Opens soon" };
const PICK_LABEL = { planned: "Planned", registered: "Registered", done: "Done" };

// Picked races stay in the data after race day; elsewhere only upcoming ones are listed.
const TODAY = new Date().toISOString().slice(0, 10);

const state = { data: null, tab: "all", view: "list", shown: PAGE, filtered: [] };
let map = null;
let cluster = null;
let pickLayer = null;

const $ = (sel) => document.querySelector(sel);
const form = $("#filter-form");

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function flag(code) {
  if (!code || code.length !== 2 || code === "XK") return "";
  return String.fromCodePoint(...[...code].map((c) => 0x1f1a5 + c.charCodeAt(0)));
}

function fmtDate(iso, opts) {
  return new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", { timeZone: "UTC", ...opts });
}

function maxKm(e) {
  return e.distances.reduce((m, d) => Math.max(m, d.km), 0);
}

function ownerPick(e) {
  return (e.picks || []).find((p) => p.person === state.data.owner);
}

function readFilters() {
  const f = new FormData(form);
  const num = (k) => (f.get(k) === "" || f.get(k) === null ? null : Number(f.get(k)));
  return {
    q: (f.get("q") || "").trim().toLowerCase(),
    region: f.get("region") || "",
    country: f.get("country") || "",
    from: f.get("from") || "",
    to: f.get("to") || "",
    disciplines: f.getAll("discipline"),
    kmin: num("kmin"),
    kmax: num("kmax"),
    emin: num("emin"),
    emax: num("emax"),
    ultra: f.get("ultra") === "on",
    open: f.get("open") === "on",
  };
}

function matches(e, f, regionCountries) {
  if (state.tab === "mine" ? !ownerPick(e) : e.end_date < TODAY) return false;
  if (f.country && e.country !== f.country) return false;
  if (regionCountries && !regionCountries.has(e.country)) return false;
  if (f.from && e.end_date < f.from) return false;
  if (f.to && e.start_date > f.to) return false;
  if (f.disciplines.length && !f.disciplines.includes(e.discipline)) return false;
  if (f.open && e.registration.status !== "open") return false;
  if (f.ultra && maxKm(e) <= MARATHON_KM) return false;

  // Distance and climb filters pass an event when any one of its distances fits.
  const needsDistance = f.kmin !== null || f.kmax !== null || f.emin !== null || f.emax !== null;
  if (needsDistance) {
    const fits = e.distances.some((d) =>
      (f.kmin === null || d.km >= f.kmin) &&
      (f.kmax === null || d.km <= f.kmax) &&
      (f.emin === null || (d.elevation_gain_m ?? -1) >= f.emin) &&
      (f.emax === null || (d.elevation_gain_m ?? Infinity) <= f.emax));
    if (!fits) return false;
  }
  if (f.q) {
    const hay = [e.name, e.city, e.country, state.data.countries[e.country]].join(" ").toLowerCase();
    if (!f.q.split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  return true;
}

function apply() {
  const f = readFilters();
  const region = state.data.regions.find((r) => r.key === f.region);
  const regionCountries = region ? new Set(region.countries) : null;
  state.filtered = state.data.events.filter((e) => matches(e, f, regionCountries));
  state.shown = PAGE;
  saveToUrl();
  render();
}

function dateBlock(e) {
  const start = fmtDate(e.start_date, { day: "numeric", month: "short" });
  const weekday = fmtDate(e.start_date, { weekday: "short" });
  if (e.end_date && e.end_date !== e.start_date) {
    const end = fmtDate(e.end_date, { day: "numeric", month: "short" });
    return `${esc(start)}<small>to ${esc(end)}</small>`;
  }
  return `${esc(start)}<small>${esc(weekday)}</small>`;
}

function distanceChips(e) {
  return e.distances
    .map((d) => {
      const km = Number.isInteger(d.km) ? d.km : d.km.toFixed(1);
      const climb = d.elevation_gain_m ? ` ↑${d.elevation_gain_m} m` : "";
      return `<span class="chip">${esc(km)} km${esc(climb)}</span>`;
    })
    .join("");
}

function card(e) {
  const pick = ownerPick(e);
  const place = [e.city, state.data.countries[e.country] || e.country].filter(Boolean).join(", ");
  const status = e.registration.status;
  const statusBadge = STATUS_LABEL[status]
    ? `<span class="badge ${esc(status)}">${esc(STATUS_LABEL[status])}</span>` : "";
  const pickBadge = pick ? `<span class="badge pick">${esc(pickText(pick))}</span>` : "";
  const sources = e.sources
    .map((s) => `<a href="${esc(s.source_url)}" rel="noopener">${esc(s.source)}</a>`)
    .join(", ");
  return `<li class="card${pick ? " picked" : ""}">
    <div class="when">${dateBlock(e)}</div>
    <h3 class="name"><a href="${esc(e.registration.url || e.source_url)}" rel="noopener">${esc(e.name)}</a></h3>
    <div class="meta"><span>${flag(e.country)} ${esc(place || "Location unknown")}</span>
      <span>${esc(e.discipline)}</span>${statusBadge}${pickBadge}</div>
    <div class="chips">${distanceChips(e)}</div>
    <details><summary>Details</summary>
      Listed by ${sources}. Event id <code>${esc(e.id)}</code> (use it in picks.yaml).
    </details>
  </li>`;
}

function renderList() {
  const list = $("#list");
  const items = state.filtered.slice(0, state.shown);
  if (!items.length) {
    list.innerHTML = `<li class="empty">${state.tab === "mine"
      ? "No picks yet — add race ids to picks.yaml." : "No races match these filters."}</li>`;
    $("#more").hidden = true;
    return;
  }
  let month = "";
  const html = [];
  for (const e of items) {
    const m = fmtDate(e.start_date, { month: "long", year: "numeric" });
    if (m !== month) {
      html.push(`<li class="month">${esc(m)}</li>`);
      month = m;
    }
    html.push(card(e));
  }
  list.innerHTML = html.join("");
  const more = $("#more");
  more.hidden = state.filtered.length <= state.shown;
  more.textContent = `Show more (${state.filtered.length - state.shown} left)`;
}

function pickText(pick) {
  return `★ ${PICK_LABEL[pick.status] || pick.status}${pick.note ? " — " + pick.note : ""}`;
}

function popup(e) {
  const when = fmtDate(e.start_date, { day: "numeric", month: "short", year: "numeric" });
  const km = e.distances.map((d) => d.km).join(" / ");
  const pick = ownerPick(e);
  return `<strong><a href="${esc(e.registration.url || e.source_url)}" rel="noopener">${esc(e.name)}</a></strong><br>
    ${esc(when)} · ${esc(e.city || "")} ${flag(e.country)}<br>${km ? esc(km) + " km" : ""}
    ${pick ? `<br><span class="pick-note">${esc(pickText(pick))}</span>` : ""}`;
}

function renderMap() {
  if (!window.L) {
    $("#map-note").hidden = false;
    $("#map-note").textContent = "The map library failed to load.";
    return;
  }
  if (!map) {
    map = L.map("map", { worldCopyJump: true }).setView([30, 20], 2);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    cluster = L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 45 });
    map.addLayer(cluster);
    // Picks stay out of the clusters, or a few stars drown among thousands of races.
    pickLayer = L.layerGroup().addTo(map);
  }
  cluster.clearLayers();
  pickLayer.clearLayers();
  const located = state.filtered.filter((e) => e.lat !== null && e.lon !== null);
  const pickIcon = L.divIcon({ className: "pick-marker", html: "★", iconSize: [26, 26] });
  const plain = [];
  for (const e of located) {
    if (ownerPick(e)) {
      L.marker([e.lat, e.lon], { icon: pickIcon, zIndexOffset: 1000 }).bindPopup(popup(e)).addTo(pickLayer);
    } else {
      plain.push(L.marker([e.lat, e.lon]).bindPopup(popup(e)));
    }
  }
  cluster.addLayers(plain);
  const missing = state.filtered.length - located.length;
  const note = $("#map-note");
  note.hidden = missing === 0;
  note.textContent = `${missing} of ${state.filtered.length} races have no known position and are only in the list. Positions are approximate (town level).`;
  setTimeout(() => map.invalidateSize(), 0);
}

function render() {
  const total = state.data.events.filter((e) => e.end_date >= TODAY).length;
  const n = state.filtered.length;
  $("#summary").textContent = state.tab === "mine"
    ? `${n} of my races` : `${n.toLocaleString("en")} of ${total.toLocaleString("en")} races`;
  $("#map").hidden = state.view !== "map";
  $("#list").hidden = state.view !== "list";
  $("#map-note").hidden = state.view !== "map";
  if (state.view === "map") {
    $("#more").hidden = true;
    renderMap();
  } else {
    renderList();
  }
}

function saveToUrl() {
  const params = new URLSearchParams();
  for (const [k, v] of new FormData(form)) if (v) params.append(k, v);
  if (state.tab !== "all") params.set("tab", state.tab);
  if (state.view !== "list") params.set("view", state.view);
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

function loadFromUrl() {
  const params = new URLSearchParams(location.search);
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") {
      el.checked = el.name === "discipline" ? params.getAll("discipline").includes(el.value) : params.get(el.name) === "on";
    } else if (params.has(el.name)) {
      el.value = params.get(el.name);
    }
  }
  state.tab = params.get("tab") === "mine" ? "mine" : "all";
  state.view = params.get("view") === "map" ? "map" : "list";
}

function setActive(selector, attr, value) {
  document.querySelectorAll(selector).forEach((b) => b.classList.toggle("active", b.dataset[attr] === value));
}

function populate() {
  const d = state.data;
  const region = form.elements.region;
  for (const r of d.regions) region.add(new Option(r.label, r.key));
  const country = form.elements.country;
  Object.entries(d.countries)
    .sort((a, b) => a[1].localeCompare(b[1]))
    .forEach(([code, name]) => country.add(new Option(`${flag(code)} ${name}`, code)));
  $("#disciplines").innerHTML = DISCIPLINES.map((x) =>
    `<label class="check"><input type="checkbox" name="discipline" value="${x}"> ${x}</label>`).join("");
  $("#mine-count").textContent = d.events.filter(ownerPick).length;

  const generated = d.generated_at ? new Date(d.generated_at).toUTCString().slice(5, 22) : "unknown";
  const sources = Object.entries(d.sources)
    .map(([name, s]) => `${esc(name)} (${s.count}${s.status !== "ok" ? ", " + esc(s.status) : ""})`)
    .join(", ");
  $("#sources-line").innerHTML = `Updated ${esc(generated)} UTC from ${sources}. <a href="https://github.com/sanchpet/races/blob/main/docs/sources.md">About the sources</a>.`;
}

function wire() {
  form.addEventListener("input", apply);
  form.addEventListener("reset", () => setTimeout(apply, 0));
  $("#more").addEventListener("click", () => {
    state.shown += PAGE;
    renderList();
  });
  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    state.tab = b.dataset.tab;
    setActive("[data-tab]", "tab", state.tab);
    apply();
  }));
  document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    state.view = b.dataset.view;
    setActive("[data-view]", "view", state.view);
    saveToUrl();
    render();
  }));
  $("#filters-toggle").addEventListener("click", (ev) => {
    const box = $("#filters");
    box.classList.toggle("open");
    ev.currentTarget.setAttribute("aria-expanded", box.classList.contains("open"));
  });
}

async function main() {
  try {
    const resp = await fetch("events.json", { cache: "no-cache" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    state.data = await resp.json();
  } catch (err) {
    $("#summary").textContent = `Could not load the calendar: ${err.message}`;
    return;
  }
  populate();
  loadFromUrl();
  setActive("[data-tab]", "tab", state.tab);
  setActive("[data-view]", "view", state.view);
  wire();
  apply();
}

main();
