// Location Timeline panel for Home Assistant (plain ES module, no build step).
// External network access: OpenStreetMap map tiles only.

const WIDE_MIN_PX = 870;
const DEFAULT_CENTER = [35.681, 139.767];

const MODES = {
  walk: { icon: "🚶", label: "徒歩", color: "#1a73e8" },
  run: { icon: "🏃", label: "ランニング", color: "#e8710a" },
  bicycle: { icon: "🚲", label: "自転車", color: "#188038" },
  car: { icon: "🚗", label: "車", color: "#5f6368" },
  bus: { icon: "🚌", label: "バス", color: "#9334e6" },
  train: { icon: "🚆", label: "電車", color: "#d93025" },
  subway: { icon: "🚇", label: "地下鉄", color: "#c5221f" },
  plane: { icon: "✈️", label: "飛行機", color: "#129eaf" },
  vehicle: { icon: "🚙", label: "乗り物", color: "#5f6368" },
  unknown: { icon: "❓", label: "移動", color: "#9aa0a6" },
};

// CARTO の basemaps は API キー必須になったので OSM 標準タイルを使う（ダーク時は CSS で反転）。
const TILE_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors';
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

const modeInfo = (mode) => MODES[mode] || MODES.unknown;

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDistance(m) {
  if (m >= 1000) return `${(m / 1000).toFixed(1)} km`;
  return `${Math.round(m)} m`;
}

function formatDuration(sec) {
  const min = Math.round(sec / 60);
  if (min < 1) return "1分未満";
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h === 0) return `${m}分`;
  return m === 0 ? `${h}時間` : `${h}時間${m}分`;
}

function todayIn(tz) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function addDays(dateStr, n) {
  const d = new Date(`${dateStr}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

const isDateStr = (s) => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s);

let leafletPromise = null;
function loadLeaflet(base) {
  if (window.L) return Promise.resolve(window.L);
  if (!leafletPromise) {
    leafletPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = `${base}/vendor/leaflet.js`;
      script.async = true;
      script.onload = () => resolve(window.L);
      script.onerror = () => {
        leafletPromise = null;
        script.remove();
        reject(new Error("Leaflet の読み込みに失敗しました"));
      };
      document.head.appendChild(script);
    });
  }
  return leafletPromise;
}

const STYLE = `
:host { display: block; height: 100vh; height: 100dvh; overflow: hidden; color: var(--primary-text-color); background: var(--primary-background-color); }
* { box-sizing: border-box; }
.root { display: flex; flex-direction: column; height: 100%; }
header {
  display: flex; align-items: center; gap: 4px; flex: none;
  min-height: calc(56px + env(safe-area-inset-top)); padding: env(safe-area-inset-top) max(4px, env(safe-area-inset-right)) 0 max(4px, env(safe-area-inset-left));
  background: var(--app-header-background-color); color: var(--app-header-text-color, white);
  border-bottom: var(--app-header-border-bottom, none);
}
header .title { font-size: 20px; margin: 0 8px 0 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 0 1 auto; }
header .spacer { flex: 1 1 auto; }
header button, header label.toggle {
  min-width: 44px; min-height: 44px; border: none; background: transparent; color: inherit;
  font: inherit; font-size: 15px; border-radius: 22px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 4px; padding: 0 8px;
}
header button.nav { font-size: 26px; padding: 0; }
header button:disabled { opacity: 0.35; cursor: default; }
header button:not(:disabled):hover, header label.toggle:hover { background: rgba(255,255,255,0.12); }
header input[type=date] {
  min-height: 36px; font: inherit; font-size: 15px; color: inherit; background: rgba(255,255,255,0.12);
  border: none; border-radius: 6px; padding: 0 6px; color-scheme: dark;
}
header label.toggle input { width: 18px; height: 18px; margin: 0; }
.body { flex: 1 1 auto; display: flex; min-height: 0; }
.list { overflow-y: auto; background: var(--card-background-color); -webkit-overflow-scrolling: touch; padding-bottom: env(safe-area-inset-bottom); }
.map { position: relative; flex: 1 1 auto; min-width: 0; min-height: 0; z-index: 0; }
.root.wide .body { flex-direction: row; }
.root.wide .list { width: 400px; flex: none; border-right: 1px solid var(--divider-color); }
.root:not(.wide) .body { flex-direction: column; }
.root:not(.wide) .map { flex: none; height: 42vh; height: 42dvh; order: -1; border-bottom: 1px solid var(--divider-color); }
.root:not(.wide) .list { flex: 1 1 0; min-height: 0; padding-left: env(safe-area-inset-left); padding-right: env(safe-area-inset-right); }
.root:not(.wide) header .title { display: none; }
.root:not(.wide) header .toggle span { font-size: 13px; }
.root.wide header .toggle .ln, .root:not(.wide) header .toggle .lw { display: none; }
header button, header label.toggle { white-space: nowrap; flex: none; }
.root:not(.wide) header input[type=date] { min-width: 0; flex: 0 1 auto; }
@media (max-width: 380px) { header .today { padding: 0 4px; } }

.status { padding: 24px 16px; color: var(--secondary-text-color); text-align: center; }
.status.error { color: var(--error-color, #db4437); }
.status button { margin-top: 12px; min-height: 44px; padding: 0 20px; border-radius: 22px; border: 1px solid var(--divider-color); background: transparent; color: var(--primary-color); font: inherit; cursor: pointer; }

.summary { padding: 16px; border-bottom: 1px solid var(--divider-color); }
.summary .total { font-size: 22px; font-weight: 500; }
.summary .sub { color: var(--secondary-text-color); font-size: 14px; margin-top: 2px; }
.summary .modes { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-top: 8px; font-size: 14px; }
.summary .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }

.items { list-style: none; margin: 0; padding: 8px 0; }
.item { display: flex; gap: 8px; padding: 0 12px 0 8px; cursor: pointer; min-height: 44px; }
.item:hover { background: rgba(127,127,127,0.08); }
.item.selected { background: rgba(var(--rgb-primary-color, 3,169,244), 0.14); }
.rail { width: 32px; flex: none; position: relative; display: flex; justify-content: center; }
.rail .line { position: absolute; top: 0; bottom: 0; width: 4px; border-radius: 2px; }
.rail .pin {
  position: relative; margin-top: 10px; width: 26px; height: 26px; border-radius: 50%;
  background: var(--primary-color); color: white; font-size: 13px; font-weight: 600;
  display: flex; align-items: center; justify-content: center; border: 2px solid var(--card-background-color);
}
.item.gap .line { border-left: 2px dashed var(--divider-color); width: 0; background: none; }
.content { flex: 1 1 auto; min-width: 0; padding: 10px 0; }
.content .name { font-size: 16px; font-weight: 500; overflow-wrap: anywhere; }
.content .area { font-size: 13px; color: var(--secondary-text-color); overflow-wrap: anywhere; }
.content .meta { font-size: 13px; color: var(--secondary-text-color); margin-top: 2px; }
.content .inferred { font-size: 11px; color: var(--secondary-text-color); margin-left: 4px; font-weight: normal; }
.item.move .content .name { font-size: 15px; }
.item.gap { cursor: default; min-height: 32px; }
.item.gap:hover { background: none; }
.item.gap .content { padding: 6px 0; font-size: 13px; color: var(--secondary-text-color); opacity: 0.7; }
.children { list-style: none; margin: 6px 0 0 0; padding: 0 0 0 12px; border-left: 2px solid var(--divider-color); }
.children li { font-size: 13px; padding: 2px 0; }
.children .cmeta { color: var(--secondary-text-color); font-size: 12px; }
.empty { padding: 32px 16px; text-align: center; color: var(--secondary-text-color); }

.lt-pin {
  width: 28px; height: 28px; border-radius: 50%; background: var(--primary-color, #03a9f4); color: white;
  border: 2px solid white; box-shadow: 0 1px 4px rgba(0,0,0,0.45); font: 600 13px/24px sans-serif; text-align: center;
}
.lt-pin.selected { transform: scale(1.3); background: #ea4335; z-index: 1000; }
.tiles-dark { filter: invert(1) hue-rotate(180deg) brightness(0.9) contrast(0.9); }
.leaflet-container { font: inherit; background: var(--secondary-background-color, #ddd); }
.leaflet-popup-content { font-size: 14px; }
`;

class LocationTimelinePanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._narrow = false;
    this._panel = null;
    this._built = false;
    this._date = null;
    this._range = null;
    this._rangeRequested = false;
    this._data = null;
    this._loading = false;
    this._error = null;
    this._requestSeq = 0;
    this._selected = null;
    this._showPoints = false;
    this._map = null;
    this._tiles = null;
    this._dark = null;
    this._layers = null;
    this._segLayers = new Map();
    this._pointLayer = null;
    this._resizeObserver = null;
    this._onKeyDown = this._handleKeyDown.bind(this);
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menuButton) this._menuButton.hass = hass;
    if (first && this.isConnected) this._start();
    this._updateTheme();
  }

  get hass() {
    return this._hass;
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menuButton) this._menuButton.narrow = narrow;
  }

  get narrow() {
    return this._narrow;
  }

  set panel(panel) {
    this._panel = panel;
  }

  get panel() {
    return this._panel;
  }

  set route(route) {
    this._route = route;
  }

  get route() {
    return this._route;
  }

  get _tz() {
    return this._data?.tz || this._hass?.config?.time_zone || "Asia/Tokyo";
  }

  get _staticBase() {
    return this._panel?.config?.static_base || "/location_timeline_static";
  }

  get _today() {
    return todayIn(this._tz);
  }

  connectedCallback() {
    this._build();
    window.addEventListener("keydown", this._onKeyDown);
    this._resizeObserver = new ResizeObserver(() => this._onResize());
    this._resizeObserver.observe(this);
    this._resizeObserver.observe(this._mapEl);
    if (this._hass) this._start();
  }

  disconnectedCallback() {
    window.removeEventListener("keydown", this._onKeyDown);
    this._resizeObserver?.disconnect();
    this._resizeObserver = null;
    if (this._map) {
      this._map.remove();
      this._map = null;
      this._tiles = null;
      this._layers = null;
      this._pointLayer = null;
      this._segLayers.clear();
      this._dark = null;
    }
  }

  // ---------------------------------------------------------------- setup

  _build() {
    if (this._built) return;
    this._built = true;
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>${STYLE}</style>
      <link rel="stylesheet" href="${esc(this._staticBase)}/vendor/leaflet.css">
      <div class="root">
        <header>
          <span class="menu"></span>
          <div class="title">タイムライン</div>
          <button class="nav prev" title="前日 (←)" aria-label="前日">‹</button>
          <input type="date" class="date" aria-label="日付">
          <button class="nav next" title="翌日 (→)" aria-label="翌日">›</button>
          <button class="today">今日</button>
          <div class="spacer"></div>
          <label class="toggle" title="点を表示"><input type="checkbox" class="points"><span class="lw">点を表示</span><span class="ln">点</span></label>
        </header>
        <div class="body">
          <div class="list"></div>
          <div class="map"></div>
        </div>
      </div>`;
    this._rootEl = root.querySelector(".root");
    this._listEl = root.querySelector(".list");
    this._mapEl = root.querySelector(".map");
    this._dateEl = root.querySelector("input.date");
    this._prevEl = root.querySelector(".prev");
    this._nextEl = root.querySelector(".next");
    this._todayEl = root.querySelector(".today");
    this._pointsEl = root.querySelector("input.points");

    this._menuButton = document.createElement("ha-menu-button");
    this._menuButton.hass = this._hass;
    this._menuButton.narrow = this._narrow;
    root.querySelector(".menu").appendChild(this._menuButton);

    this._prevEl.addEventListener("click", () => this._shiftDate(-1));
    this._nextEl.addEventListener("click", () => this._shiftDate(1));
    this._todayEl.addEventListener("click", () => this._setDate(this._today));
    this._dateEl.addEventListener("change", () => {
      if (isDateStr(this._dateEl.value)) this._setDate(this._dateEl.value);
    });
    this._pointsEl.addEventListener("change", () => {
      this._showPoints = this._pointsEl.checked;
      this._renderPoints();
    });
    this._listEl.addEventListener("click", (ev) => this._onListClick(ev));
    this._rootEl.classList.toggle("wide", this.clientWidth >= WIDE_MIN_PX);
  }

  _start() {
    if (!this._date) {
      const fromUrl = new URL(window.location.href).searchParams.get("date");
      this._date = isDateStr(fromUrl) && fromUrl <= this._today ? fromUrl : this._today;
    }
    this._ensureMap();
    if (!this._rangeRequested) {
      this._rangeRequested = true;
      this._fetchRange();
    }
    if (!this._data && !this._loading) {
      this._load();
    } else {
      this._updateHeader();
      this._renderList();
      this._renderMap(false);
    }
  }

  async _ensureMap() {
    if (this._map) return;
    let L;
    try {
      L = await loadLeaflet(this._staticBase);
    } catch (err) {
      this._error = err.message;
      this._renderList();
      return;
    }
    if (this._map || !this.isConnected) return;
    this._map = L.map(this._mapEl, { zoomControl: true, attributionControl: true }).setView(
      DEFAULT_CENTER,
      11,
    );
    this._layers = L.layerGroup().addTo(this._map);
    const stopAutoFit = () => {
      this._autoFit = false;
    };
    this._mapEl.addEventListener("pointerdown", stopAutoFit, { passive: true });
    this._mapEl.addEventListener("wheel", stopAutoFit, { passive: true });
    this._updateTheme();
    this._renderMap(true);
  }

  _updateTheme() {
    if (!this._map || !this._hass) return;
    const dark = Boolean(this._hass.themes?.darkMode);
    if (dark === this._dark) return;
    this._dark = dark;
    if (this._tiles) this._tiles.remove();
    this._tiles = window.L.tileLayer(TILE_URL, {
      attribution: TILE_ATTRIBUTION,
      maxNativeZoom: 19,
      maxZoom: 20,
      className: dark ? "tiles-dark" : "",
    }).addTo(this._map);
  }

  _onResize() {
    const wide = this.clientWidth >= WIDE_MIN_PX;
    if (this._rootEl && this._rootEl.classList.contains("wide") !== wide) {
      this._rootEl.classList.toggle("wide", wide);
    }
    if (!this._map) return;
    this._map.invalidateSize();
    if (this._autoFit && this._selected === null) {
      clearTimeout(this._fitTimer);
      this._fitTimer = setTimeout(() => this._autoFit && this._fitAll(), 80);
    }
  }

  _handleKeyDown(ev) {
    if (ev.defaultPrevented || ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
    if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
    const path = ev.composedPath();
    const typing = path.some(
      (el) =>
        el instanceof HTMLElement &&
        (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable),
    );
    if (typing || this.offsetParent === null) return;
    ev.preventDefault();
    this._shiftDate(ev.key === "ArrowLeft" ? -1 : 1);
  }

  // ---------------------------------------------------------------- data

  async _fetchRange() {
    try {
      this._range = await this._hass.callApi("GET", "location_timeline/range");
    } catch (_err) {
      this._range = null;
    }
    this._updateHeader();
  }

  _shiftDate(n) {
    if (this._date) this._setDate(addDays(this._date, n));
  }

  _setDate(dateStr) {
    const today = this._today;
    let next = dateStr > today ? today : dateStr;
    const first = this._range?.first;
    if (isDateStr(first) && next < first) next = first;
    if (next === this._date && this._data) {
      this._updateHeader();
      return;
    }
    this._date = next;
    this._load();
  }

  async _load() {
    const seq = ++this._requestSeq;
    const date = this._date;
    this._loading = true;
    this._error = null;
    this._selected = null;
    this._syncUrl();
    this._updateHeader();
    this._renderList();
    try {
      const data = await this._hass.callApi("GET", `location_timeline/day?date=${date}`);
      if (seq !== this._requestSeq) return;
      this._data = data;
    } catch (err) {
      if (seq !== this._requestSeq) return;
      this._data = null;
      this._error = err?.body?.error || err?.body?.message || err?.message || "読み込みに失敗しました";
    }
    this._loading = false;
    this._updateHeader();
    this._renderList();
    this._renderMap(true);
  }

  _syncUrl() {
    const url = new URL(window.location.href);
    if (url.searchParams.get("date") === this._date) return;
    url.searchParams.set("date", this._date);
    window.history.replaceState(window.history.state, "", url.toString());
  }

  _updateHeader() {
    if (!this._built || !this._date) return;
    const today = this._today;
    const first = isDateStr(this._range?.first) ? this._range.first : "";
    this._dateEl.value = this._date;
    this._dateEl.max = today;
    this._dateEl.min = first;
    this._nextEl.disabled = this._date >= today;
    this._prevEl.disabled = Boolean(first) && this._date <= first;
    this._todayEl.disabled = this._date === today;
  }

  // ---------------------------------------------------------------- list

  _fmtTime(ts) {
    if (!this._timeFmt || this._timeFmtTz !== this._tz) {
      this._timeFmtTz = this._tz;
      this._timeFmt = new Intl.DateTimeFormat("ja-JP", {
        timeZone: this._tz,
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      });
    }
    return this._timeFmt.format(new Date(ts * 1000));
  }

  _timeRange(seg) {
    const start = seg.start_clipped ? "前日から" : this._fmtTime(seg.start);
    let end;
    if (seg.ongoing) end = `現在（最終更新 ${this._fmtTime(seg.end)}）`;
    else if (seg.end_clipped) end = "翌日へ";
    else end = this._fmtTime(seg.end);
    return `${start} – ${end}`;
  }

  _stayTitle(s) {
    if (s.name) return s.name;
    if (s.area) return `${s.area}付近`;
    return "滞在";
  }

  _renderList() {
    if (!this._built) return;
    if (this._loading) {
      this._listEl.innerHTML = `<div class="status">読み込み中…</div>`;
      return;
    }
    if (this._error) {
      this._listEl.innerHTML = `<div class="status error">${esc(this._error)}<br><button class="retry">再試行</button></div>`;
      this._listEl.querySelector(".retry").addEventListener("click", () => {
        if (!this._map) this._ensureMap();
        this._load();
      });
      return;
    }
    const data = this._data;
    if (!data) {
      this._listEl.innerHTML = "";
      return;
    }
    const segs = data.segments || [];
    const real = segs.filter((s) => s.type !== "gap");
    if (real.length === 0) {
      this._listEl.innerHTML = `<div class="empty">この日の記録はありません</div>`;
      return;
    }
    const html = [this._summaryHtml(data), `<ul class="items">`];
    let stayNo = 0;
    segs.forEach((seg, idx) => {
      if (seg.type === "stay") html.push(this._stayHtml(seg, idx, ++stayNo));
      else if (seg.type === "move") html.push(this._moveHtml(seg, idx));
      else html.push(this._gapHtml(seg));
    });
    html.push("</ul>");
    this._listEl.innerHTML = html.join("");
    this._applySelection(false);
  }

  _summaryHtml(data) {
    const sum = data.summary || {};
    const dist = sum.distance_m || {};
    const total = Object.values(dist).reduce((a, b) => a + b, 0);
    const modes = Object.entries(dist)
      .filter(([, m]) => m > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([mode, m]) => {
        const info = modeInfo(mode);
        return `<span><span class="dot" style="background:${info.color}"></span>${info.icon} ${esc(info.label)} ${formatDistance(m)}</span>`;
      })
      .join("");
    const moveTime = sum.move_seconds ? ` · 移動 ${formatDuration(sum.move_seconds)}` : "";
    return `<div class="summary">
      <div class="total">${formatDistance(total)}</div>
      <div class="sub">滞在 ${Number(sum.stay_count) || 0} か所${moveTime}</div>
      ${modes ? `<div class="modes">${modes}</div>` : ""}
    </div>`;
  }

  _stayHtml(s, idx, no) {
    const children = (s.children || [])
      .map(
        (c) =>
          `<li>${esc(this._stayTitle(c))} <span class="cmeta">${this._fmtTime(c.start)} – ${this._fmtTime(c.end)}</span></li>`,
      )
      .join("");
    return `<li class="item stay" data-idx="${idx}">
      <div class="rail"><div class="pin">${no}</div></div>
      <div class="content">
        <div class="name">${esc(this._stayTitle(s))}</div>
        ${s.name && s.area ? `<div class="area">${esc(s.area)}</div>` : ""}
        <div class="meta">${this._timeRange(s)} · ${formatDuration(s.end - s.start)}</div>
        ${children ? `<ul class="children">${children}</ul>` : ""}
      </div>
    </li>`;
  }

  _moveHtml(m, idx) {
    const info = modeInfo(m.mode);
    const inferred = m.mode_inferred ? `<span class="inferred">(推定)</span>` : "";
    return `<li class="item move" data-idx="${idx}">
      <div class="rail"><div class="line" style="background:${info.color}"></div></div>
      <div class="content">
        <div class="name">${info.icon} ${esc(info.label)}${inferred}</div>
        <div class="meta">${formatDistance(m.distance_m || 0)} · ${formatDuration(m.end - m.start)}</div>
        <div class="meta">${this._timeRange(m)}</div>
      </div>
    </li>`;
  }

  _gapHtml(g) {
    return `<li class="item gap">
      <div class="rail"><div class="line"></div></div>
      <div class="content">記録なし ${this._fmtTime(g.start)} – ${this._fmtTime(g.end)}</div>
    </li>`;
  }

  _onListClick(ev) {
    const item = ev.target.closest(".item[data-idx]");
    if (!item) return;
    this._select(Number(item.dataset.idx), "list");
  }

  // ---------------------------------------------------------------- map

  _renderMap(fit) {
    if (!this._map || !this._layers) return;
    const L = window.L;
    this._layers.clearLayers();
    this._segLayers.clear();
    this._pointLayer = null;
    const data = this._data;
    if (!data) return;
    const segs = data.segments || [];
    let stayNo = 0;
    segs.forEach((seg, idx) => {
      if (seg.type === "move" && (seg.path || []).length >= 2) {
        const latlngs = seg.path.map((p) => [p[0], p[1]]);
        const color = modeInfo(seg.mode).color;
        const casing = L.polyline(latlngs, { color: "#ffffff", weight: 9, opacity: 0.9 });
        const line = L.polyline(latlngs, { color, weight: 5, opacity: 0.95 });
        const onClick = () => this._select(idx, "map");
        casing.on("click", onClick);
        line.on("click", onClick);
        casing.addTo(this._layers);
        line.addTo(this._layers);
        this._segLayers.set(idx, { type: "move", casing, line, color });
      }
    });
    segs.forEach((seg, idx) => {
      if (seg.type !== "stay") return;
      stayNo += 1;
      const icon = L.divIcon({
        className: "",
        html: `<div class="lt-pin">${stayNo}</div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      });
      const marker = L.marker([seg.lat, seg.lon], { icon, riseOnHover: true });
      marker.bindPopup(
        `<b>${esc(this._stayTitle(seg))}</b><br>${seg.name && seg.area ? `${esc(seg.area)}<br>` : ""}${this._timeRange(seg)}`,
      );
      marker.on("click", () => this._select(idx, "map"));
      marker.addTo(this._layers);
      this._segLayers.set(idx, { type: "stay", marker });
    });
    this._renderPoints();
    this._applySelection(false);
    if (fit) this._fitAll();
  }

  _renderPoints() {
    if (!this._map) return;
    if (this._pointLayer) {
      this._pointLayer.remove();
      this._pointLayer = null;
    }
    if (!this._showPoints || !this._data) return;
    const L = window.L;
    this._pointLayer = L.layerGroup(
      (this._data.points || []).map((p) =>
        L.circleMarker([p[0], p[1]], {
          radius: 3,
          weight: 0,
          fillColor: "#5f6368",
          fillOpacity: 0.45,
          interactive: false,
        }),
      ),
    ).addTo(this._map);
  }

  _fitAll() {
    const data = this._data;
    if (!this._map || !data) return;
    // レイアウト確定前（サイズ 0 や切替途中）に合わせるとズームが狂うので、
    // ユーザーが地図を動かすまではリサイズのたびに合わせ直す。
    this._map.invalidateSize();
    this._autoFit = true;
    const size = this._map.getSize();
    if (size.x < 50 || size.y < 50) return;
    const segs = (data.segments || []).filter((s) => s.type !== "gap");
    if (segs.length === 1 && segs[0].type === "stay") {
      this._map.setView([segs[0].lat, segs[0].lon], 16);
      return;
    }
    if (data.bounds) this._map.fitBounds(data.bounds, { padding: [32, 32], maxZoom: 17 });
  }

  // ---------------------------------------------------------------- selection

  _select(idx, from) {
    this._selected = idx;
    this._applySelection(from === "map");
    const seg = this._data?.segments?.[idx];
    const layer = this._segLayers.get(idx);
    if (!seg || !this._map) return;
    if (from === "list") {
      if (seg.type === "stay") {
        this._map.setView([seg.lat, seg.lon], 17);
        layer?.marker.openPopup();
      } else if (seg.type === "move" && layer) {
        this._map.fitBounds(layer.line.getBounds(), { padding: [32, 32], maxZoom: 18 });
      }
    }
  }

  _applySelection(scroll) {
    const sel = this._selected;
    for (const el of this._listEl.querySelectorAll(".item.selected")) el.classList.remove("selected");
    if (sel !== null) {
      const el = this._listEl.querySelector(`.item[data-idx="${sel}"]`);
      if (el) {
        el.classList.add("selected");
        if (scroll) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    }
    for (const [idx, layer] of this._segLayers) {
      const active = idx === sel;
      if (layer.type === "move") {
        layer.line.setStyle({ weight: active ? 8 : 5, opacity: sel === null || active ? 0.95 : 0.55 });
        layer.casing.setStyle({ weight: active ? 12 : 9 });
        if (active) {
          layer.casing.bringToFront();
          layer.line.bringToFront();
        }
      } else {
        layer.marker.getElement()?.firstElementChild?.classList.toggle("selected", active);
        layer.marker.setZIndexOffset(active ? 1000 : 0);
      }
    }
  }
}

if (!customElements.get("location-timeline-panel")) {
  customElements.define("location-timeline-panel", LocationTimelinePanel);
}
