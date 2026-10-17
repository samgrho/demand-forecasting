"use strict";

// ---------- helpers ----------

const $ = (sel) => document.querySelector(sel);
const SVG_NS = "http://www.w3.org/2000/svg";
const LEVEL_VARS = { "Quiet": "--lvl-quiet", "Normal": "--lvl-normal", "Busy": "--lvl-busy", "Very busy": "--lvl-very" };
const KIND_LABEL = { event: "Event", holiday: "Public holiday", long_weekend: "Long weekend" };
const OUTCOME_ICON = { ok: "✓", cached: "✓", skipped: "–", blocked: "⦸", error: "✕" };
const STORAGE_KEY = "hdf-form-v1";

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

function link(url, text) {
  const href = safeUrl(url);
  if (!href) return esc(text);
  return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer nofollow">${esc(text)}</a>`;
}

const parseDay = (iso) => new Date(iso + "T00:00:00");
const fmtDay = (iso, opts = { weekday: "short", month: "short", day: "numeric" }) => parseDay(iso).toLocaleDateString(undefined, opts);
const fmtStamp = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function fmtRange(start, end) {
  if (start === end) return fmtDay(start);
  return `${fmtDay(start)} – ${fmtDay(end)}`;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function levelSwatch(level) {
  return `<span class="swatch" style="background:var(${LEVEL_VARS[level]})" aria-hidden="true"></span>`;
}

function citations(sources) {
  if (!sources || !sources.length) return `<span class="muted">no source</span>`;
  return `<span class="cite">` + sources.map((s) => {
    const href = safeUrl(s.url);
    const title = `Fetched ${fmtStamp(s.fetched_at)}`;
    return href
      ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer nofollow" title="${esc(title)}">${esc(s.publisher)} ↗</a>`
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

// ---------- form ----------

const form = $("#forecast-form");
const statusEl = $("#status");
let state = { data: null, selected: null, kind: "all" };

function isoToday(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toLocaleDateString("en-CA"); // YYYY-MM-DD in local time
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
      if (saved.source_urls) form.querySelector(".sources-input").open = true;
    }
  } catch { /* storage unavailable: start blank */ }
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

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  saveForm();
  const btn = $("#submit-btn");
  btn.disabled = true;
  statusEl.className = "status";
  statusEl.textContent = "Checking sources… requests are spaced out to be polite to each site, so this can take up to a minute.";
  const body = {
    location: form.location.value.trim(),
    start: form.start.value,
    end: form.end.value,
    radius_km: Number(form.radius_km.value),
    source_urls: form.source_urls.value.split(/\s+/).map((s) => s.trim()).filter(Boolean),
  };
  try {
    const res = await fetch("/api/forecast", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail;
      throw new Error(detail || `Request failed (${res.status})`);
    }
    state = { data, selected: null, kind: "all" };
    statusEl.textContent = `Forecast built ${fmtStamp(data.generated_at)} from ${data.sources.length} sources.`;
    render();
  } catch (err) {
    statusEl.className = "status error";
    statusEl.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

// ---------- render ----------

function render() {
  const d = state.data;
  $("#results").hidden = false;
  $("#warnings").innerHTML = d.warnings.map((w) => `<div class="warning">${esc(w)}</div>`).join("");
  $("#loc-line").innerHTML = `${link(d.location.source_url, d.location.display_name)} · ${fmtRange(d.request.start, d.request.end)} · events within ${d.request.radius_km} km`;
  renderPeriods();
  renderLegend();
  renderChart();
  renderDayDetail();
  renderDaysTable();
  renderSignals();
  renderSeason();
  renderLog();
  renderMethod();
}

function signalLine(sig, extra = "") {
  const when = fmtRange(sig.start, sig.end);
  const where = sig.venue ? ` · ${esc(sig.venue)}` : "";
  return `<strong>${esc(sig.title)}</strong> <span class="muted">(${esc(when)}${where})</span>${extra} ${citations(sig.sources)}`;
}

function renderPeriods() {
  const { periods, signals } = state.data;
  const list = $("#periods");
  if (!periods.length) {
    list.innerHTML = `<li class="empty">No busy stretches found in this range from the sources checked. Add local event pages above, or connect Ticketmaster, to look further.</li>`;
    return;
  }
  list.innerHTML = periods.map((p) => {
    const top = p.signal_ids.slice(0, 4).map((id) => `<li>${signalLine(signals[id])}</li>`).join("");
    const more = p.signal_ids.length > 4 ? `<li class="muted">+ ${p.signal_ids.length - 4} more — select the day in the chart for the full list</li>` : "";
    return `<li class="period">
      <div class="score">${Math.round(p.peak_score)}<small>peak</small></div>
      <h3>${esc(fmtRange(p.start, p.end))} <span class="level">${levelSwatch(p.level)}${esc(p.level)}</span></h3>
      <ul class="drivers">${top}${more}</ul>
    </li>`;
  }).join("");
}

function renderLegend() {
  const levels = state.data.model.levels.slice().reverse();
  $("#legend").innerHTML = levels.map((l) => `<span>${levelSwatch(l.name)}${esc(l.name)} ${l.min ? `(${l.min}+)` : ""}</span>`).join("")
    + `<span><span class="line-key" aria-hidden="true"></span>Seasonal baseline</span>`;
}

function renderChart() {
  const svg = $("#chart");
  const box = svg.parentElement;
  const tip = $("#tooltip");
  const days = state.data.days;
  const signals = state.data.signals;
  svg.innerHTML = "";

  const W = box.clientWidth;
  const H = svg.clientHeight || 280;
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
      const r = svg.getBoundingClientRect();
      const sx = r.width / W;
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

function selectDay(i) {
  state.selected = i;
  renderChart();
  renderDayDetail();
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

function renderDayDetail() {
  const box = $("#day-detail");
  if (state.selected == null) { box.innerHTML = ""; return; }
  const d = state.data.days[state.selected];
  const signals = state.data.signals;
  const items = d.drivers.map((dr) => {
    const s = signals[dr.signal_id];
    const role = dr.role === "arrival night" ? ` <span class="muted">— night before; visitors arriving</span>` : "";
    return `<li>${signalLine(s, role)} <span class="muted">· +${dr.contribution.toFixed(2)}</span></li>`;
  }).join("");
  box.innerHTML = `<div class="panel">
    <h3>${esc(fmtDay(d.day, { weekday: "long", month: "long", day: "numeric", year: "numeric" }))} — ${Math.round(d.score)}/100 <span class="level">${levelSwatch(d.level)}${esc(d.level)}</span></h3>
    <p class="muted">Seasonal baseline ${d.baseline.toFixed(0)} (month factor ×${d.seasonal_factor.toFixed(2)}); signal pressure ${d.pressure.toFixed(2)}.</p>
    ${items ? `<ul>${items}</ul>` : `<p class="empty">No events or holidays found for this day.</p>`}
  </div>`;
}

function renderDaysTable() {
  const { days, signals } = state.data;
  $("#days-table").innerHTML = `<thead><tr><th>Date</th><th class="num">Index</th><th>Level</th><th class="num">Baseline</th><th>Drivers</th></tr></thead><tbody>`
    + days.map((d) => `<tr>
      <td class="date">${esc(fmtDay(d.day))}</td>
      <td class="num">${Math.round(d.score)}</td>
      <td>${levelSwatch(d.level)} ${esc(d.level)}</td>
      <td class="num">${Math.round(d.baseline)}</td>
      <td>${d.drivers.map((dr) => esc(signals[dr.signal_id].title)).join("; ") || `<span class="muted">—</span>`}</td>
    </tr>`).join("") + `</tbody>`;
}

function renderSignals() {
  const { signals } = state.data;
  const rows = signals.filter((s) => state.kind === "all" || s.kind === state.kind);
  const table = $("#signals-table");
  if (!rows.length) {
    table.innerHTML = `<tbody><tr><td class="empty">Nothing of this kind found in the range.</td></tr></tbody>`;
    return;
  }
  table.innerHTML = `<thead><tr><th>Dates</th><th>What</th><th>Type</th><th>Where</th><th class="num">Impact</th><th>Sources</th></tr></thead><tbody>`
    + rows.map((s) => `<tr>
      <td class="date">${esc(fmtRange(s.start, s.end))}</td>
      <td><strong>${esc(s.title)}</strong>${s.description ? `<span class="sub-line">${esc(s.description)}</span>` : ""}</td>
      <td>${esc(s.category || KIND_LABEL[s.kind] || s.kind)}</td>
      <td>${esc(s.venue || "—")}${s.distance_km != null ? `<span class="sub-line">${s.distance_km} km away</span>` : ""}</td>
      <td class="num">${s.weight.toFixed(2)}</td>
      <td>${s.sources.map((src) => `<div>${citations([src])}<span class="sub-line">fetched ${esc(fmtStamp(src.fetched_at))}</span></div>`).join("")}</td>
    </tr>`).join("") + `</tbody>`;
}

document.querySelectorAll(".filter").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.kind = btn.dataset.kind;
    document.querySelectorAll(".filter").forEach((b) => {
      b.classList.toggle("is-on", b === btn);
      b.setAttribute("aria-pressed", String(b === btn));
    });
    if (state.data) renderSignals();
  });
});

function renderSeason() {
  const seasonal = state.data.seasonal;
  const svg = $("#season-chart");
  const box = svg.parentElement;
  const tip = $("#season-tooltip");
  svg.innerHTML = "";
  if (!seasonal) {
    $("#season-note").textContent = "No Wikipedia or Wikivoyage page found for this location, so every month uses the same baseline.";
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const site = seasonal.project.replace(".", ".") + ".org";
  $("#season-note").innerHTML = `Relative monthly readership of the ${esc(site)} page “${esc(seasonal.page_title)}” over the last 3 years (1.0 = average month), used to shift the baseline. A proxy for trip-planning interest, not bookings. ${citations([seasonal.source])}`;

  const W = box.clientWidth;
  const H = svg.clientHeight || 200;
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
    const name = new Date(2000, i, 1).toLocaleDateString(undefined, { month: "short" });
    const label = el("text", { x: m.left + i * slot + slot / 2, y: H - 6, "text-anchor": "middle" });
    label.textContent = name;
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
  $("#method-text").innerHTML = `${esc(m.note)} Each day starts at a seasonal baseline (${m.baseline} × that month's travel-interest factor). Every event, holiday or long weekend covering the day adds pressure according to its type and distance; large events also add pressure to the night before, when visitors check in. Pressure raises the index with diminishing returns, so one more small event on an already-busy day barely moves it. Impact weights are rough rules of thumb, not fitted to your bookings. Treat the index as a prompt to check those dates, and verify each event through its source link.`;
}

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (state.data) { renderChart(); renderSeason(); } }, 150);
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (state.data) { renderChart(); renderSeason(); } });

restoreForm();
