"use strict";

// ---------- helpers ----------

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const SVG_NS = "http://www.w3.org/2000/svg";
const LEVEL_VARS = { "Quiet": "--lvl-quiet", "Normal": "--lvl-normal", "Busy": "--lvl-busy", "Very busy": "--lvl-very" };
const KIND_LABEL = { event: "Event", holiday: "Public holiday", long_weekend: "Long weekend" };
const OUTCOME_ICON = { ok: "✓", cached: "✓", skipped: "–", blocked: "⦸", error: "✕" };
const SHORT_LABEL = { "Venue capacity": "venue size", "Artist popularity": "artist popularity" };
const STORAGE_KEY = "hdf-form-v1";
const SECTIONS_KEY = "hdf-sections-v1";

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

function link(url, text, title = "") {
  const href = safeUrl(url);
  if (!href) return esc(text);
  return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer nofollow"${title ? ` title="${esc(title)}"` : ""}>${esc(text)}</a>`;
}

const parseDay = (iso) => new Date(iso + "T00:00:00");
const fmtDay = (iso, opts = { weekday: "short", month: "short", day: "numeric" }) => parseDay(iso).toLocaleDateString(undefined, opts);
const fmtLong = (iso) => fmtDay(iso, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
const fmtStamp = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function fmtRange(start, end) {
  if (start === end) return fmtDay(start);
  return `${fmtDay(start)} – ${fmtDay(end)}`;
}

function fmtRangeShort(start, end) {
  const a = parseDay(start), b = parseDay(end);
  const md = { month: "short", day: "numeric" };
  if (start === end) return a.toLocaleDateString(undefined, md);
  if (a.getMonth() === b.getMonth()) return `${a.toLocaleDateString(undefined, md)}–${b.getDate()}`;
  return `${a.toLocaleDateString(undefined, md)} – ${b.toLocaleDateString(undefined, md)}`;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function levelSwatch(level) {
  return `<span class="swatch" style="background:var(${LEVEL_VARS[level]})" aria-hidden="true"></span>`;
}

function levelTag(level) {
  return `<span class="level">${levelSwatch(level)}${esc(level)}</span>`;
}

function citations(sources) {
  if (!sources || !sources.length) return `<span class="muted">no source</span>`;
  return `<span class="cite">` + sources.map((s) => {
    const href = safeUrl(s.url);
    return href
      ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer nofollow" title="Fetched ${esc(fmtStamp(s.fetched_at))}">${esc(s.publisher)} ↗</a>`
      : esc(s.publisher);
  }).join("") + `</span>`;
}

function el(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function barPath(x, y, w, h, r) {
  if (h <= 0) return "";
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function placeTooltip(tip, box, x, y) {
  tip.hidden = false;
  const bw = box.clientWidth;
  const tw = tip.offsetWidth;
  let left = x + 12;
  if (left + tw > bw) left = Math.max(0, x - tw - 12);
  tip.style.left = `${left}px`;
  tip.style.top = `${Math.max(0, y - 10)}px`;
}

// ---------- state ----------

const form = $("#forecast-form");
const statusEl = $("#status");
let state = { data: null, selected: null, kind: "all", query: "", bigOnly: false, view: "chart" };

const dayIndex = (iso) => state.data.days.findIndex((d) => d.day === iso);

// ---------- query bar ----------

function isoToday(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toLocaleDateString("en-CA"); // YYYY-MM-DD in local time
}

function sourceUrls() {
  return form.source_urls.value.split(/\s+/).map((s) => s.trim()).filter(Boolean);
}

function updatePagesCount() {
  const n = sourceUrls().length;
  $("#pages-count").textContent = n ? `(${n})` : "";
}

function restoreForm() {
  form.start.value = isoToday(0);
  form.end.value = isoToday(90);
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (saved) {
      form.location.value = saved.location || "";
      form.radius_km.value = saved.radius_km || 25;
      form.source_urls.value = saved.source_urls || "";
    }
  } catch { /* storage unavailable: start blank */ }
  updatePagesCount();
}

function saveForm() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      location: form.location.value,
      radius_km: form.radius_km.value,
      source_urls: form.source_urls.value,
    }));
  } catch { /* ignore */ }
}

$("#pages-toggle").addEventListener("click", () => {
  const panel = $("#pages-panel");
  panel.hidden = !panel.hidden;
  $("#pages-toggle").setAttribute("aria-expanded", String(!panel.hidden));
  if (!panel.hidden) form.source_urls.focus();
});
form.source_urls.addEventListener("input", updatePagesCount);

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  saveForm();
  const btn = $("#submit-btn");
  btn.disabled = true;
  btn.classList.add("is-loading");
  statusEl.className = "status";
  statusEl.textContent = "Checking sources… requests are spaced out to be polite to each site, so the first run for a city can take up to a minute.";
  const body = {
    location: form.location.value.trim(),
    start: form.start.value,
    end: form.end.value,
    radius_km: Number(form.radius_km.value),
    source_urls: sourceUrls(),
  };
  try {
    const res = await fetch("/api/forecast", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail;
      throw new Error(detail || `Request failed (${res.status})`);
    }
    const peak = data.days.reduce((best, d, i) => (d.score > data.days[best].score ? i : best), 0);
    state = { ...state, data, selected: data.days.length ? peak : null, kind: "all", query: "", bigOnly: false };
    $("#events-search").value = "";
    $("#events-big").checked = false;
    $$(".filter").forEach((b) => { b.classList.toggle("is-on", b.dataset.kind === "all"); b.setAttribute("aria-pressed", String(b.dataset.kind === "all")); });
    statusEl.textContent = "";
    $("#pages-panel").hidden = true;
    $("#pages-toggle").setAttribute("aria-expanded", "false");
    render();
  } catch (err) {
    statusEl.className = "status error";
    statusEl.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.classList.remove("is-loading");
  }
});

// ---------- render ----------

function render() {
  const d = state.data;
  $("#empty-state").hidden = true;
  $("#results").hidden = false;
  $("#warnings").innerHTML = d.warnings.map((w) => `<div class="warning">${esc(w)}</div>`).join("");
  $("#loc-line").innerHTML = `${link(d.location.source_url, d.location.display_name)} · ${esc(fmtRange(d.request.start, d.request.end))} · events within ${d.request.radius_km} km · built ${esc(fmtStamp(d.generated_at))} from ${d.sources.length} sources`;
  renderKpis();
  renderPeriods();
  renderLegend();
  renderChart();
  renderDaysTable();
  renderDayStrip();
  renderDayDetail();
  renderSignals();
  renderLog();
  renderMethod();
  $("#events-count").textContent = `(${d.signals.length})`;
  $("#log-count").textContent = `(${d.source_log.length})`;
  if ($("#sec-season").open) renderSeason();
}

function sizeLine(sig) {
  if (!sig.adjustments || !sig.adjustments.length) return "";
  return `<div class="adj-line">` + sig.adjustments.map((a) => a.sources.length
    ? `${esc(a.detail)} ${citations(a.sources)}`
    : `${esc(a.detail)} <span class="assumption" title="Not a sourced claim: a rule of the model">(model assumption)</span>`
  ).join(`<span class="sep">·</span>`) + `</div>`;
}

function signalLine(sig, extra = "") {
  const when = fmtRange(sig.start, sig.end);
  const where = sig.venue ? ` · ${esc(sig.venue)}` : "";
  return `<strong>${esc(sig.title)}</strong> <span class="muted">(${esc(when)}${where})</span>${extra} ${citations(sig.sources)}${sizeLine(sig)}`;
}

function impactCell(s) {
  const notes = (s.adjustments || []).map((a) => `<span class="sub-line${a.sources.length ? "" : " muted"}">×${a.factor.toFixed(2)} ${esc(SHORT_LABEL[a.label] || a.label.toLowerCase())}${a.sources.length ? "" : " (assumed)"}</span>`);
  if (s.kind === "event") {
    const has = (label) => (s.adjustments || []).some((a) => a.label === label);
    if (!has("Venue capacity")) notes.push(`<span class="sub-line muted">venue size unknown</span>`);
    const sports = (s.category || "").startsWith("Sports");
    if (s.performers && s.performers.length && !sports && !has("Artist popularity")) notes.push(`<span class="sub-line muted">artist popularity unknown</span>`);
  }
  const base = s.adjustments && s.adjustments.length ? `<span class="sub-line">base ${s.base_weight.toFixed(2)}</span>` : "";
  return `${s.weight.toFixed(2)}${base}${notes.join("")}`;
}

// --- stat tiles

function tile(label, value, sub) {
  return `<div class="tile-label">${esc(label)}</div><div class="tile-value">${value}</div><div class="tile-sub">${sub}</div>`;
}

function dayButton(iso, text) {
  return `<button type="button" class="tile-link" data-day="${esc(iso)}">${esc(text)}</button>`;
}

function renderKpis() {
  const { days, periods, signals } = state.data;
  const peak = days.reduce((a, b) => (b.score > a.score ? b : a), days[0]);
  const peakTop = peak.drivers[0] ? signals[peak.drivers[0].signal_id].title : "seasonal baseline only";
  $("#kpi-peak").innerHTML = tile("Peak day", `${Math.round(peak.score)}${levelSwatch(peak.level)}<small>${esc(peak.level)}</small>`,
    `${dayButton(peak.day, fmtDay(peak.day))} · ${esc(peakTop)}`);

  const today = isoToday(0);
  const next = periods.filter((p) => p.end >= today).sort((a, b) => a.start.localeCompare(b.start))[0];
  $("#kpi-next").innerHTML = next
    ? tile("Next busy stretch", esc(fmtRangeShort(next.start, next.end)),
      `${dayButton(next.peak_day, `peak ${Math.round(next.peak_score)}`)} · ${esc(signals[next.signal_ids[0]]?.title || "")}`)
    : tile("Next busy stretch", "None", "no busy stretch in this range");

  const busy = days.filter((d) => d.level === "Busy" || d.level === "Very busy").length;
  const very = days.filter((d) => d.level === "Very busy").length;
  $("#kpi-busy").innerHTML = tile("Busy days", `${busy}<small>of ${days.length}</small>`, `${very} very busy`);

  const events = signals.filter((s) => s.kind === "event");
  const venueSized = events.filter((s) => s.adjustments.some((a) => a.label === "Venue capacity" && a.sources.length)).length;
  const artistSized = events.filter((s) => s.adjustments.some((a) => a.label === "Artist popularity")).length;
  const holidays = signals.length - events.length;
  $("#kpi-events").innerHTML = tile("Events found", `${events.length}<small>+ ${holidays} holiday/travel</small>`,
    `${venueSized} sized by venue · ${artistSized} by artist`);
}

document.querySelector(".kpis").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-day]");
  if (btn) selectDay(dayIndex(btn.dataset.day), { showTab: true });
});

// --- busiest dates

function renderPeriods() {
  const { periods, signals } = state.data;
  const list = $("#periods");
  $("#periods-count").textContent = periods.length ? `${periods.length} stretch${periods.length === 1 ? "" : "es"}, ranked by peak` : "";
  if (!periods.length) {
    list.innerHTML = `<li class="empty">No busy stretches found from the sources checked. Add local event pages or connect Ticketmaster to look further.</li>`;
    return;
  }
  const selectedDay = state.selected != null ? state.data.days[state.selected].day : null;
  list.innerHTML = periods.map((p) => {
    const top = p.signal_ids.slice(0, 3).map((id) => {
      const s = signals[id];
      return `<li>${link(s.sources[0]?.url, s.title, `${s.sources[0]?.publisher || ""} · ${fmtRange(s.start, s.end)}`)}</li>`;
    }).join("");
    const more = p.signal_ids.length > 3 ? `<li class="muted">+${p.signal_ids.length - 3} more</li>` : "";
    const active = selectedDay && selectedDay >= p.start && selectedDay <= p.end ? " is-active" : "";
    return `<li class="period${active}" data-day="${esc(p.peak_day)}" tabindex="0">
      <div class="score">${Math.round(p.peak_score)}<small>peak</small></div>
      <h3>${esc(fmtRange(p.start, p.end))} ${levelTag(p.level)}</h3>
      <ul class="drivers">${top}${more}</ul>
    </li>`;
  }).join("");
}

$("#periods").addEventListener("click", (e) => {
  if (e.target.closest("a")) return; // source links open normally
  const item = e.target.closest(".period");
  if (item) selectDay(dayIndex(item.dataset.day), { showTab: true });
});
$("#periods").addEventListener("keydown", (e) => {
  const item = e.target.closest(".period");
  if (item && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); selectDay(dayIndex(item.dataset.day), { showTab: true }); }
});

// --- chart

function renderLegend() {
  const levels = state.data.model.levels.slice().reverse();
  $("#legend").innerHTML = levels.map((l) => `<span>${levelSwatch(l.name)}${esc(l.name)}${l.min ? ` ${l.min}+` : ""}</span>`).join("")
    + `<span><span class="line-key" aria-hidden="true"></span>Seasonal baseline</span>`;
}

function renderChart() {
  const svg = $("#chart");
  const box = svg.parentElement;
  const tip = $("#tooltip");
  const days = state.data.days;
  const signals = state.data.signals;
  svg.innerHTML = "";
  if (box.hidden || !box.clientWidth) return;

  const W = box.clientWidth;
  const H = svg.clientHeight || 300;
  const m = { top: 10, right: 8, bottom: 26, left: 32 };
  const iw = W - m.left - m.right;
  const ih = H - m.top - m.bottom;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const y = (v) => m.top + ih - (v / 100) * ih;
  const slot = iw / days.length;
  const bw = Math.max(1, Math.min(24, slot - 2));
  const xAt = (i) => m.left + i * slot + (slot - bw) / 2;

  for (const t of [0, 25, 50, 75, 100]) {
    svg.append(el("line", { class: t === 0 ? "axis" : "grid", x1: m.left, x2: W - m.right, y1: y(t), y2: y(t) }));
    const label = el("text", { x: m.left - 6, y: y(t) + 4, "text-anchor": "end" });
    label.textContent = t;
    svg.append(label);
  }

  // x-axis labels: month starts, plus weekly ticks on short ranges
  const short = days.length <= 45;
  let lastLabelEnd = -Infinity;
  days.forEach((d, i) => {
    const date = parseDay(d.day);
    const isMonthStart = date.getDate() === 1 || i === 0;
    const isWeekTick = short && date.getDay() === 1;
    if (!isMonthStart && !isWeekTick) return;
    const cx = i === 0 ? m.left : m.left + i * slot + slot / 2;
    const text = el("text", { x: cx, y: H - 8, "text-anchor": i === 0 ? "start" : "middle" });
    text.textContent = isMonthStart && !short
      ? date.toLocaleDateString(undefined, { month: "short", ...(date.getMonth() === 0 || i === 0 ? { year: "numeric" } : {}) })
      : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    svg.append(text);
    // Drop any label that would collide with the previous one or run off the edge.
    const { x, width } = text.getBBox();
    if (x < lastLabelEnd + 8 || x + width > W) { text.remove(); return; }
    lastLabelEnd = x + width;
  });

  const bars = [];
  days.forEach((d, i) => {
    const top = y(d.score);
    const bar = el("path", {
      class: "bar" + (state.selected === i ? " is-selected" : ""),
      d: barPath(xAt(i), top, bw, y(0) - top, bw >= 6 ? 4 : 1),
      fill: cssVar(LEVEL_VARS[d.level]),
    });
    svg.append(bar);
    bars.push(bar);
  });

  // seasonal baseline as a step line
  let pathD = "";
  days.forEach((d, i) => {
    const x0 = m.left + i * slot;
    pathD += `${i === 0 ? "M" : "L"}${x0},${y(d.baseline)}H${x0 + slot}`;
  });
  svg.append(el("path", { class: "baseline-line", d: pathD }));

  // hit targets: full column, wider than the bar
  days.forEach((d, i) => {
    const hit = el("rect", { class: "hit", x: m.left + i * slot, y: m.top, width: Math.max(slot, 1), height: ih });
    hit.addEventListener("mouseenter", () => {
      svg.classList.add("has-hover");
      bars[i].classList.add("is-hover");
      tip.innerHTML = dayTooltip(d, signals);
      const sx = svg.getBoundingClientRect().width / W;
      placeTooltip(tip, box, (m.left + i * slot + slot / 2) * sx, y(d.score) * sx);
    });
    hit.addEventListener("mouseleave", () => {
      svg.classList.remove("has-hover");
      bars[i].classList.remove("is-hover");
      tip.hidden = true;
    });
    hit.addEventListener("click", () => selectDay(i));
    svg.append(hit);
  });

  svg.setAttribute("tabindex", "0");
  svg.setAttribute("aria-label", `Daily demand index, ${days.length} days. Use left and right arrow keys to step through days.`);
}

function dayTooltip(d, signals) {
  const drivers = d.drivers.slice(0, 3).map((dr) => {
    const s = signals[dr.signal_id];
    return `<li>${esc(s.title)}${dr.role === "arrival night" ? " (arrivals)" : ""}</li>`;
  }).join("");
  const more = d.drivers.length > 3 ? `<li>+${d.drivers.length - 3} more</li>` : "";
  return `<strong>${esc(fmtDay(d.day, { weekday: "long", month: "short", day: "numeric", year: "numeric" }))}</strong>
    ${Math.round(d.score)}/100 · ${esc(d.level)}
    ${drivers ? `<ul>${drivers}${more}</ul>` : `<div class="muted">Seasonal baseline only</div>`}`;
}

$("#chart").addEventListener("keydown", (e) => {
  if (!state.data) return;
  const n = state.data.days.length;
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    e.preventDefault();
    const cur = state.selected ?? (e.key === "ArrowRight" ? -1 : n);
    selectDay(Math.min(n - 1, Math.max(0, cur + (e.key === "ArrowRight" ? 1 : -1))));
    $("#chart").focus();
  }
});

$$(".seg-btn").forEach((btn) => btn.addEventListener("click", () => {
  state.view = btn.dataset.view;
  $$(".seg-btn").forEach((b) => { b.classList.toggle("is-on", b === btn); b.setAttribute("aria-pressed", String(b === btn)); });
  $("#chart-view").hidden = state.view !== "chart";
  $("#table-view").hidden = state.view !== "table";
  $("#legend").hidden = state.view !== "chart";
  if (state.view === "chart") renderChart();
}));

function renderDaysTable() {
  const { days, signals } = state.data;
  $("#days-table").innerHTML = `<thead><tr><th>Date</th><th class="num">Index</th><th>Level</th><th class="num">Baseline</th><th>Drivers</th></tr></thead><tbody>`
    + days.map((d, i) => `<tr class="clickable" data-index="${i}">
      <td class="date">${esc(fmtDay(d.day))}</td>
      <td class="num">${Math.round(d.score)}</td>
      <td>${levelTag(d.level)}</td>
      <td class="num">${Math.round(d.baseline)}</td>
      <td>${d.drivers.slice(0, 4).map((dr) => esc(signals[dr.signal_id].title)).join("; ") || `<span class="muted">—</span>`}${d.drivers.length > 4 ? ` <span class="muted">+${d.drivers.length - 4}</span>` : ""}</td>
    </tr>`).join("") + `</tbody>`;
}

$("#days-table").addEventListener("click", (e) => {
  const row = e.target.closest("tr[data-index]");
  if (row) selectDay(Number(row.dataset.index), { showTab: true });
});

// --- selection

function selectDay(i, { showTab = false } = {}) {
  if (i == null || i < 0) return;
  state.selected = i;
  renderChart();
  renderPeriods();
  renderDayStrip();
  renderDayDetail();
  if (showTab) {
    const sec = $("#sec-day");
    sec.open = true;
    sec.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function renderDayStrip() {
  const strip = $("#day-strip");
  if (state.selected == null) {
    strip.innerHTML = `<span class="muted">Select a bar to see what's driving that day.</span>`;
    return;
  }
  const d = state.data.days[state.selected];
  const top = d.drivers.slice(0, 2).map((dr) => esc(state.data.signals[dr.signal_id].title)).join("; ");
  strip.innerHTML = `<strong>${esc(fmtDay(d.day, { weekday: "short", month: "short", day: "numeric", year: "numeric" }))}</strong>
    <span>${Math.round(d.score)}/100 ${levelTag(d.level)}</span>
    <span class="muted">${top ? `Top: ${top}${d.drivers.length > 2 ? ` +${d.drivers.length - 2} more` : ""}` : "Seasonal baseline only"}</span>
    <button type="button" class="tile-link" id="strip-details">Full breakdown ↓</button>`;
  $("#strip-details").addEventListener("click", () => selectDay(state.selected, { showTab: true }));
}

function renderDayDetail() {
  const box = $("#day-detail");
  const summary = $("#day-summary");
  if (state.selected != null) {
    const sd = state.data.days[state.selected];
    summary.innerHTML = `${esc(fmtDay(sd.day))} · ${Math.round(sd.score)} ${levelTag(sd.level)}`;
  } else {
    summary.textContent = "Everything driving one day's score";
  }
  if (state.selected == null) {
    box.innerHTML = `<p class="empty">Select a day in the chart, a busy stretch, or an event to see the full breakdown.</p>`;
    return;
  }
  const d = state.data.days[state.selected];
  const signals = state.data.signals;
  const items = d.drivers.map((dr) => {
    const s = signals[dr.signal_id];
    const role = dr.role === "arrival night" ? ` <span class="muted">— night before; visitors arriving</span>` : "";
    return `<li><span class="contrib">+${dr.contribution.toFixed(2)}</span><div>${signalLine(s, role)}</div></li>`;
  }).join("");
  const routine = d.routine_excluded > 0
    ? ` ${d.routine_excluded.toFixed(2)} of that is set aside as routine (a typical ${esc(fmtDay(d.day, { weekday: "long" }))} in this range), leaving ${d.pressure.toFixed(2)}.`
    : "";
  const raw = d.pressure + (d.routine_excluded || 0);
  box.innerHTML = `
    <div class="day-head">
      <span class="big">${Math.round(d.score)}</span>
      <h3>${esc(fmtLong(d.day))}</h3>
      ${levelTag(d.level)}
    </div>
    <p class="sub">Seasonal baseline ${d.baseline.toFixed(0)} (month factor ×${d.seasonal_factor.toFixed(2)}). Signals add ${raw.toFixed(2)} of pressure.${routine}</p>
    ${items ? `<ul class="driver-list">${items}</ul>` : `<p class="empty">No events or holidays found for this day.</p>`}`;
}

// --- events table

function signalMatches(s) {
  if (state.kind !== "all" && s.kind !== state.kind) return false;
  if (state.bigOnly && s.weight < 1) return false;
  if (!state.query) return true;
  const hay = [s.title, s.venue, s.category, s.description, ...(s.performers || []).map((p) => p.name)].join(" ").toLowerCase();
  return hay.includes(state.query);
}

function renderSignals() {
  const rows = state.data.signals.filter(signalMatches);
  const table = $("#signals-table");
  if (!rows.length) {
    table.innerHTML = `<tbody><tr><td class="empty">Nothing matches these filters.</td></tr></tbody>`;
    return;
  }
  table.innerHTML = `<thead><tr><th>Dates</th><th>What</th><th>Type</th><th>Where</th><th class="num">Impact</th><th>Sources</th></tr></thead><tbody>`
    + rows.map((s) => `<tr class="clickable" data-day="${esc(s.start)}">
      <td class="date">${esc(fmtRange(s.start, s.end))}</td>
      <td><strong>${esc(s.title)}</strong>${s.description ? `<span class="sub-line">${esc(s.description)}</span>` : ""}</td>
      <td>${esc(s.category || KIND_LABEL[s.kind] || s.kind)}</td>
      <td>${esc(s.venue || "—")}${s.distance_km != null ? `<span class="sub-line">${s.distance_km} km away</span>` : ""}</td>
      <td class="num impact">${impactCell(s)}</td>
      <td>${sizeLine(s)}${s.sources.map((src) => `<div>${citations([src])}<span class="sub-line">fetched ${esc(fmtStamp(src.fetched_at))}</span></div>`).join("")}</td>
    </tr>`).join("") + `</tbody>`;
}

$("#signals-table").addEventListener("click", (e) => {
  if (e.target.closest("a")) return;
  const row = e.target.closest("tr[data-day]");
  if (!row) return;
  // multi-day signals may start before the range; fall back to the first day
  const i = dayIndex(row.dataset.day);
  selectDay(i >= 0 ? i : 0, { showTab: true });
});

$$(".filter").forEach((btn) => btn.addEventListener("click", () => {
  state.kind = btn.dataset.kind;
  $$(".filter").forEach((b) => { b.classList.toggle("is-on", b === btn); b.setAttribute("aria-pressed", String(b === btn)); });
  if (state.data) renderSignals();
}));
$("#events-search").addEventListener("input", (e) => {
  state.query = e.target.value.trim().toLowerCase();
  if (state.data) renderSignals();
});
$("#events-big").addEventListener("change", (e) => {
  state.bigOnly = e.target.checked;
  if (state.data) renderSignals();
});

// --- collapsible report sections

function saveSections() {
  try {
    localStorage.setItem(SECTIONS_KEY, JSON.stringify(Object.fromEntries($$(".section").map((sec) => [sec.dataset.section, sec.open]))));
  } catch { /* ignore */ }
}

function restoreSections() {
  try {
    const saved = JSON.parse(localStorage.getItem(SECTIONS_KEY) || "null");
    if (saved) $$(".section").forEach((sec) => { if (sec.dataset.section in saved) sec.open = saved[sec.dataset.section]; });
  } catch { /* storage unavailable: keep defaults */ }
}

$$(".section").forEach((sec) => sec.addEventListener("toggle", () => {
  saveSections();
  // the seasonality chart needs a visible box to measure
  if (sec.id === "sec-season" && sec.open && state.data) renderSeason();
}));
$("#expand-all").addEventListener("click", () => $$(".section").forEach((sec) => { sec.open = true; }));
$("#collapse-all").addEventListener("click", () => $$(".section").forEach((sec) => { sec.open = false; }));

// --- seasonality

function renderSeason() {
  const seasonal = state.data.seasonal;
  const svg = $("#season-chart");
  const box = $("#season-box");
  const tip = $("#season-tooltip");
  svg.innerHTML = "";
  if (!seasonal) {
    $("#season-note").textContent = "No Wikipedia or Wikivoyage page found for this location, so every month uses the same baseline.";
    box.hidden = true;
    return;
  }
  box.hidden = false;
  $("#season-note").innerHTML = `Relative monthly readership of the ${esc(seasonal.project)}.org page “${esc(seasonal.page_title)}” over the last 3 years (1.0 = an average month). It shifts each day's baseline: a proxy for trip-planning interest, not bookings. ${citations([seasonal.source])}`;
  if (!box.clientWidth) return;

  const W = box.clientWidth;
  const H = svg.clientHeight || 210;
  const m = { top: 10, right: 8, bottom: 24, left: 32 };
  const iw = W - m.left - m.right;
  const ih = H - m.top - m.bottom;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const values = Array.from({ length: 12 }, (_, i) => seasonal.month_index[String(i + 1)] ?? 1);
  const maxV = Math.max(1.5, Math.ceil(Math.max(...values) * 4) / 4);
  const y = (v) => m.top + ih - (v / maxV) * ih;
  for (let t = 0; t <= maxV + 1e-9; t += 0.5) {
    svg.append(el("line", { class: t === 0 ? "axis" : "grid", x1: m.left, x2: W - m.right, y1: y(t), y2: y(t) }));
    const label = el("text", { x: m.left - 6, y: y(t) + 4, "text-anchor": "end" });
    label.textContent = t.toFixed(1);
    svg.append(label);
  }
  svg.append(el("line", { class: "baseline-line", x1: m.left, x2: W - m.right, y1: y(1), y2: y(1) }));
  const slot = iw / 12;
  const bw = Math.min(24, slot - 2);
  const fill = cssVar("--accent");
  values.forEach((v, i) => {
    const x = m.left + i * slot + (slot - bw) / 2;
    const bar = el("path", { class: "bar", d: barPath(x, y(v), bw, y(0) - y(v), 4), fill });
    svg.append(bar);
    const label = el("text", { x: m.left + i * slot + slot / 2, y: H - 6, "text-anchor": "middle" });
    label.textContent = new Date(2000, i, 1).toLocaleDateString(undefined, { month: "short" });
    svg.append(label);
    const hit = el("rect", { class: "hit", x: m.left + i * slot, y: m.top, width: slot, height: ih });
    hit.addEventListener("mouseenter", () => {
      svg.classList.add("has-hover");
      bar.classList.add("is-hover");
      tip.innerHTML = `<strong>${esc(new Date(2000, i, 1).toLocaleDateString(undefined, { month: "long" }))}</strong>×${v.toFixed(2)} of an average month`;
      const sx = svg.getBoundingClientRect().width / W;
      placeTooltip(tip, box, (m.left + i * slot + slot / 2) * sx, y(v) * sx);
    });
    hit.addEventListener("mouseleave", () => {
      svg.classList.remove("has-hover");
      bar.classList.remove("is-hover");
      tip.hidden = true;
    });
    svg.append(hit);
  });
}

// --- log + method

function renderLog() {
  const log = state.data.source_log;
  $("#log-table").innerHTML = `<thead><tr><th>Result</th><th>Source</th><th>Request</th><th>Detail</th><th>When</th></tr></thead><tbody>`
    + log.map((c) => `<tr>
      <td><span class="outcome outcome-${esc(c.outcome)}"><i aria-hidden="true">${OUTCOME_ICON[c.outcome] || "•"}</i>${esc(c.outcome)}</span></td>
      <td>${esc(c.source)}</td>
      <td class="url">${c.url && !c.url.includes("REDACTED") && safeUrl(c.url) ? link(c.url, c.url) : esc(c.url || "—")}</td>
      <td>${esc(c.detail)}</td>
      <td class="date">${esc(fmtStamp(c.at))}</td>
    </tr>`).join("") + `</tbody>`;
}

function renderMethod() {
  const m = state.data.model;
  $("#method-text").innerHTML = `
    <p>${esc(m.note)} Treat it as a prompt to check those dates, and verify each event through its source link.</p>
    <h3>Baseline</h3>
    <p>Each day starts at ${m.baseline} × that month's travel-interest factor (Wikipedia readership of the destination; see Seasonality).</p>
    <h3>Signals</h3>
    <p>Every event, holiday or long weekend covering the day adds pressure according to its type and distance from the hotel. Large events also add pressure to the night before, when visitors check in.</p>
    <h3>Event size</h3>
    <p>Venue capacity comes from Wikidata or the venue's Wikipedia infobox: about ×0.5 for a 100-seat room, up to ×1.7 for a stadium. For non-sports events, the headliner's popularity comes from average monthly Wikipedia views: ×0.75 for little-known acts, up to ×1.6 for global stars. Venues found in neither are assumed small (×0.7) and marked as an assumption. Combined sizing is capped at ×0.4–×2.5.</p>
    <h3>Routine event load</h3>
    <p>A city's normal nightly shows are treated as part of the baseline, so only pressure above an ordinary day raises the index. For ranges of four weeks or more, each day is compared with the typical day of the same weekday (a Saturday against other Saturdays). For two to four weeks it's compared with the typical day overall.</p>
    <h3>Scale</h3>
    <p>Pressure raises the index with diminishing returns, so one more small event on an already-busy day barely moves it. Levels: ${m.levels.slice().reverse().map((l) => `${esc(l.name)}${l.min ? ` ${l.min}+` : ""}`).join(", ")}. Weights are rules of thumb, not fitted to your bookings.</p>`;
}

// ---------- settings ----------

const settingsDlg = $("#settings-dialog");
const settingsForm = $("#settings-form");
const settingsStatus = $("#settings-status");
let removeKey = false;

function setSettingsStatus(text, kind = "") {
  settingsStatus.textContent = text;
  settingsStatus.className = `dlg-status ${kind}`;
}

function applySettingsView(view) {
  const tm = $("#chip-tm"), contact = $("#chip-contact");
  tm.className = `chip ${view.ticketmaster.set ? "chip-on" : "chip-off"}`;
  tm.title = view.ticketmaster.set ? "Ticketmaster key saved" : "Add a Ticketmaster key in Settings";
  contact.className = `chip ${view.contact ? "chip-on" : "chip-off"}`;
  contact.title = view.contact ? "Contact email saved" : "Add your contact email in Settings";
  const banner = $("#setup-banner");
  if (banner && view.contact) banner.remove();
}

async function openSettings() {
  setSettingsStatus("");
  removeKey = false;
  let view;
  try {
    view = await (await fetch("/api/settings")).json();
  } catch {
    setSettingsStatus("Couldn't load settings.", "err");
    settingsDlg.showModal();
    return;
  }
  settingsForm.contact.value = view.contact || "";
  settingsForm.ticketmaster_api_key.value = "";
  settingsForm.ticketmaster_api_key.type = "password";
  $("#tm-show").textContent = "Show";
  $("#tm-saved").textContent = view.ticketmaster.set ? `(saved, ending ${view.ticketmaster.hint})` : "(not set)";
  $("#tm-remove").hidden = !view.ticketmaster.set;
  $("#settings-where").textContent = `Version ${view.version} · saved in ${view.settings_path}`;
  settingsDlg.showModal();
  settingsForm.contact.focus();
}

document.addEventListener("click", (e) => {
  if (e.target.closest("[data-open-settings]")) openSettings();
  else if (e.target.closest("[data-close-settings]")) settingsDlg.close();
});

$("#tm-show").addEventListener("click", () => {
  const input = settingsForm.ticketmaster_api_key;
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  $("#tm-show").textContent = show ? "Hide" : "Show";
  $("#tm-show").setAttribute("aria-pressed", String(show));
});

$("#tm-remove").addEventListener("click", () => {
  removeKey = true;
  settingsForm.ticketmaster_api_key.value = "";
  setSettingsStatus("The saved Ticketmaster key will be removed when you save.");
});

settingsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = { contact: settingsForm.contact.value.trim() };
  const key = settingsForm.ticketmaster_api_key.value.trim();
  if (key) body.ticketmaster_api_key = key;
  else if (removeKey) body.ticketmaster_api_key = "";
  const save = $("#settings-save");
  save.disabled = true;
  save.classList.add("is-loading");
  setSettingsStatus(key ? "Checking the key with Ticketmaster…" : "Saving…");
  try {
    const res = await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail;
      throw new Error(detail || `Couldn't save (${res.status})`);
    }
    applySettingsView(data);
    const note = data.ticketmaster_check === "valid" ? " Ticketmaster key verified."
      : data.ticketmaster_check === "unreachable" ? " Couldn't reach Ticketmaster to check the key; it was saved anyway." : "";
    setSettingsStatus(`Saved.${note} Build the forecast again to use the new settings.`, "ok");
    setTimeout(() => { if (settingsDlg.open) settingsDlg.close(); }, data.ticketmaster_check === "unreachable" ? 2600 : 1400);
  } catch (err) {
    setSettingsStatus(err.message, "err");
  } finally {
    save.disabled = false;
    save.classList.remove("is-loading");
  }
});

// ---------- boot ----------

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (!state.data) return;
    renderChart();
    if ($("#sec-season").open) renderSeason();
  }, 150);
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!state.data) return;
  renderChart();
  if ($("#sec-season").open) renderSeason();
});

restoreForm();
restoreSections();
