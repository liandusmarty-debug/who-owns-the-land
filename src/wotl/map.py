"""Web export: a self-contained static site in outputs/ (map.html + one compact data file).

Design for low-end devices:
  * geometry simplified in metres and coordinates rounded (~1 m) before publishing
  * attributes packed into short keys / arrays, not verbose GeoJSON properties
  * data shipped as a plain <script> (works from file://, USB stick, or any static host)
"""

from __future__ import annotations

import json
import shutil
from datetime import date

import numpy as np
import shapely

from .ownership import UNMAPPED
from .pipeline import Context, Stage


def _num(v: object, nd: int = 1) -> float | None:
    """Round for JSON; NaN/NA/None -> null."""
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else round(f, nd)


class WebExporter:
    def __init__(self, tolerance_m: float, precision: int, metric_crs: str, storage_crs: str) -> None:
        self.tol, self.prec, self.metric, self.storage = tolerance_m, precision, metric_crs, storage_crs

    def geometries(self, gdf) -> list[dict]:
        g = gdf.geometry.to_crs(self.metric).simplify(self.tol, preserve_topology=True).to_crs(self.storage)
        g = shapely.transform(g.values, lambda c: np.round(c, self.prec))
        return [shapely.geometry.mapping(x) for x in g]

    def build(self, ctx: Context) -> dict:
        cfg = ctx.config
        a = ctx["areas"]
        own_cols = ctx["ownership_columns"]
        ind_cols = [f"pct_{s.key}" for s in cfg.indicators]
        feats = []
        for geom, row in zip(self.geometries(a), a.itertuples(index=False), strict=False):
            r = row._asdict()
            sup = bool(r["suppressed"])
            feats.append(
                {
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "c": r["sal_code"],
                        "n": r["area_name"],
                        "w": r["ward_id"],
                        "s": None if r["settlement"] is None or r["settlement"] != r["settlement"] else r["settlement"],
                        "h": None if sup else _num(r["households"], 0),
                        "q": None if sup else _num(r["deprivation_quintile"], 0),
                        "r": None if sup else _num(r["deprivation_rank"], 0),
                        "x": None if sup else _num(r["deprivation_index"], 2),
                        "i": [None if sup else _num(r[c]) for c in ind_cols],
                        "o": [_num(r[c]) for c in own_cols],
                        "d": r["dominant_owner"] if isinstance(r["dominant_owner"], str) else None,
                        "z": int(sup),
                    },
                }
            )
        return {
            "meta": {
                "generated": date.today().isoformat(),
                "sample": ctx.sample_mode,
                "areas": len(a),
                "ranked": int(a["deprivation_rank"].notna().sum()),
                "quintiles": cfg.quintiles,
                "indicators": [s.label for s in cfg.indicators],
                "owners": [*cfg.owner_categories, UNMAPPED],
                "pilot": cfg.pilot_name,
                "caveats": ctx.tables.get("caveats_all", []),
            },
            "type": "FeatureCollection",
            "features": feats,
        }

    def write(self, ctx: Context) -> None:
        out = ctx.outputs_dir
        src = ctx.config.paths.web_src
        (out / "data").mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.build(ctx), separators=(",", ":"), ensure_ascii=False)
        (out / "data" / "areas.js").write_text(f"window.WOTL={payload};", encoding="utf-8")
        for page in ("map.html", "index.html"):  # index.html so any static host serves it at /
            shutil.copyfile(src / "index.html", out / page)
        for name in ("app.js", "style.css"):
            shutil.copyfile(src / name, out / name)
        shutil.copytree(src / "vendor", out / "vendor", dirs_exist_ok=True)


class MapStage(Stage):
    name = "web map"

    def run(self, ctx: Context) -> None:
        cfg = ctx.config
        WebExporter(cfg.simplify_tolerance_m, cfg.coord_precision, cfg.metric_crs, cfg.storage_crs).write(ctx)
