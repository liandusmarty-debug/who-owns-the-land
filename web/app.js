/* Who Owns the Land? — map front end.
 * Vanilla JS + Leaflet (canvas renderer). No build step, no framework, works from file://.
 * Data: window.WOTL = { meta, features[] } with compact keys (see src/wotl/map.py).
 */
(function () {
  "use strict";

  const DATA = window.WOTL;
  if (!DATA) { document.getElementById("detail").textContent = "Map data not found. Run `wotl build`."; return; }
  const META = DATA.meta;
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n, d = 0) => (n == null ? "—" : Number(n).toLocaleString("en-ZA", { maximumFractionDigits: d }));

  class Palette {
    constructor() { this.refresh(); }
    refresh() {
      this.quintile = [1, 2, 3, 4, 5].map((i) => css(`--q${i}`));
      this.none = css("--qna");
      this.owner = META.owners.map((_, i) => css(`--o${i}`));
    }
    forQuintile(q) { return q ? this.quintile[Math.min(q, 5) - 1] : this.none; }
    forOwner(name) { const i = META.owners.indexOf(name); return i < 0 ? this.none : this.owner[i]; }
  }

  class Legend {
    constructor(el, palette) { this.el = el; this.palette = palette; }
    render(mode) {
      const p = this.palette;
      const items = mode === "dep"
        ? [[p.quintile[4], "Most deprived 20%"], [p.quintile[3], "More deprived"], [p.quintile[2], "Middle"], [p.quintile[1], "Less deprived"],
           [p.quintile[0], "Least deprived 20%"], [p.none, "Too few households to show"]]
        : META.owners.map((o, i) => [p.owner[i], o === "Unmapped" ? "Unmapped (roads, gaps)" : o]);
      const title = mode === "dep" ? "Living conditions compared across the city" : "Main owner of the land";
      this.el.innerHTML = `<div class="legend"><h2>${title}</h2><ul>${items
        .map(([c, t]) => `<li><span class="sw" style="background:${c}"></span>${esc(t) || "&nbsp;"}</li>`).join("")}</ul></div>`;
    }
  }

  class DetailPanel {
    constructor(el, palette) { this.el = el; this.palette = palette; }
    show(p) {
      const sup = p.z === 1;
      const bars = META.indicators.map((label, i) => {
        const v = p.i[i];
        return `<div class="row"><span>${esc(label)}</span><span class="v">${v == null ? "—" : v.toFixed(0) + "%"}</span>
          <div class="track"><div class="fill" style="width:${v ?? 0}%"></div></div></div>`;
      }).join("");
      const stack = META.owners.map((o, i) => p.o[i] > 0
        ? `<span title="${esc(o)} ${p.o[i]}%" style="width:${p.o[i]}%;background:${this.palette.owner[i]}"></span>` : "").join("");
      const ownRows = META.owners.map((o, i) => p.o[i] > 0.5
        ? `<li><span class="sw" style="background:${this.palette.owner[i]}"></span>${esc(o)} — ${p.o[i].toFixed(0)}%</li>` : "").join("");
      this.el.innerHTML = `
        <h2>${esc(p.s || p.w || "Small area")}</h2>
        <p class="sub">${esc(p.w || "")} · Small area ${esc(p.c)}</p>
        ${sup ? `<p class="hint">Fewer households live here than our privacy threshold, so living-condition figures are hidden.</p>` : `
        <div class="kpis">
          <div class="kpi"><b>${fmt(p.r)} <small>of ${fmt(META.ranked)}</small></b><span>Rank (1 = most deprived)</span></div>
          <div class="kpi"><b>${fmt(p.h)}</b><span>Households</span></div>
        </div>
        <h2>Living conditions</h2>${bars}`}
        <h2 style="margin-top:14px">Who owns the land here</h2>
        <div class="stack">${stack}</div>
        <ul class="legend" style="list-style:none;padding:0;margin:0">${ownRows}</ul>`;
    }
  }

  class MapView {
    constructor() {
      this.palette = new Palette();
      this.mode = "dep";
      this.legend = new Legend(document.getElementById("legend"), this.palette);
      this.detail = new DetailPanel(document.getElementById("detail"), this.palette);
      this.map = L.map("map", { preferCanvas: true, zoomSnap: 0.5, attributionControl: true });
      this.renderer = L.canvas({ padding: 0.3, tolerance: 4 });
      this.selected = null;
      this.addBasemap();
      this.layer = L.geoJSON(DATA, {
        renderer: this.renderer,
        style: (f) => this.style(f),
        onEachFeature: (f, l) => l.on("click", () => this.select(l)),
      }).addTo(this.map);
      this.map.fitBounds(this.layer.getBounds(), { padding: [10, 10] });
      this.legend.render(this.mode);
    }

    addBasemap() {
      // Optional context tiles; the map still works offline without them.
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, opacity: 0.55, attribution: "&copy; OpenStreetMap contributors",
      }).addTo(this.map);
    }

    fill(p) { return this.mode === "dep" ? this.palette.forQuintile(p.q) : this.palette.forOwner(p.d); }

    style(f) {
      return { renderer: this.renderer, weight: 0.4, color: css("--line"), fillColor: this.fill(f.properties), fillOpacity: 0.72 };
    }

    setMode(mode) {
      this.mode = mode;
      this.layer.setStyle((f) => this.style(f));
      if (this.selected) this.highlight(this.selected);
      this.legend.render(mode);
    }

    highlight(l) { l.setStyle({ weight: 2.5, color: css("--text") }); l.bringToFront(); }

    select(l) {
      if (this.selected) this.layer.resetStyle(this.selected);
      this.selected = l;
      this.highlight(l);
      this.detail.show(l.feature.properties);
    }

    find(query) {
      const q = query.trim().toLowerCase();
      if (!q) return;
      const hits = [];
      this.layer.eachLayer((l) => {
        const p = l.feature.properties;
        if ([p.s, p.w, p.c].some((v) => v && String(v).toLowerCase() === q)) hits.push(l);
      });
      if (!hits.length) return;
      this.map.fitBounds(L.featureGroup(hits).getBounds(), { maxZoom: 16, padding: [20, 20] });
      // open the most deprived match
      hits.sort((a, b) => (a.feature.properties.r ?? 1e9) - (b.feature.properties.r ?? 1e9));
      this.select(hits[0]);
    }
  }

  // ---- wire up ------------------------------------------------------------
  const view = new MapView();

  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
    view.setMode(b.dataset.mode);
  }));

  const names = new Set();
  DATA.features.forEach((f) => { if (f.properties.s) names.add(f.properties.s); if (f.properties.w) names.add(f.properties.w); });
  document.getElementById("places").innerHTML = [...names].sort().map((n) => `<option value="${esc(n)}">`).join("");
  const search = document.getElementById("search");
  search.addEventListener("change", () => view.find(search.value));
  search.addEventListener("keydown", (e) => { if (e.key === "Enter") view.find(search.value); });

  if (META.sample) {
    const b = document.getElementById("banner");
    b.textContent = "Development preview: this map shows SYNTHETIC sample data, not real Cape Town figures.";
    b.hidden = false;
  }
  document.getElementById("about").innerHTML = `
    <p>Built from public data on ${esc(META.generated)}. Shows ${fmt(META.areas)} Census 2011 small areas (2011 baseline),
    ${fmt(META.ranked)} of them ranked. Only area-level figures are shown; no individual or household is identifiable.</p>
    <p>The living-conditions score combines: ${META.indicators.map(esc).join("; ")}.</p>
    <ul>${META.caveats.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`;

  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { view.palette.refresh(); view.setMode(view.mode); });
})();
