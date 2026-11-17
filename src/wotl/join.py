"""Join: census -> SAL polygons, then attach ward and informal-settlement context."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from .pipeline import Context, Stage


class JoinStage(Stage):
    name = "join"

    def __init__(self, settlement_min_share: float = 0.25) -> None:
        # a SAL counts as "in" a settlement if at least this share of its area overlaps it
        self.settlement_min_share = settlement_min_share

    def run(self, ctx: Context) -> None:
        cfg = ctx.config
        sal: gpd.GeoDataFrame = ctx["sal_boundaries"].merge(ctx["census"], on=cfg.census_key, how="left")
        unmatched = int(sal["households"].isna().sum())
        if unmatched:
            ctx.tables.setdefault("caveats", []).append(
                f"{unmatched} SAL polygons had no matching census record."
            )

        metric = sal.to_crs(cfg.metric_crs)
        sal["area_km2"] = (metric.area / 1e6).astype("float32")

        # ward: the ward containing each SAL's representative point (cheap, robust)
        pts = gpd.GeoDataFrame({"_i": sal.index}, geometry=metric.representative_point(), crs=cfg.metric_crs)
        wards = ctx["wards"].to_crs(cfg.metric_crs)
        hit = gpd.sjoin(pts, wards[["ward_id", "geometry"]], predicate="within", how="left")
        sal["ward_id"] = hit.drop_duplicates("_i").set_index("_i")["ward_id"].reindex(sal.index)

        # informal settlement: largest-overlap settlement above the threshold
        stl = ctx["informal_settlements"].to_crs(cfg.metric_crs)
        ov = gpd.overlay(metric[["sal_code", "geometry"]], stl[["name", "geometry"]], how="intersection",
                         keep_geom_type=True)
        sal["settlement"] = pd.NA
        sal["settlement_share"] = 0.0
        if len(ov):
            ov["a"] = ov.area
            ov = ov.sort_values("a", ascending=False).drop_duplicates("sal_code")
            share = ov.set_index("sal_code")["a"] / metric.set_index("sal_code").area.reindex(ov["sal_code"]).values
            sal["settlement_share"] = sal["sal_code"].map(share).fillna(0).astype("float32")
            name = ov.set_index("sal_code")["name"]
            sal["settlement"] = sal["sal_code"].map(name).where(sal["settlement_share"] >= self.settlement_min_share)

        ctx["areas"] = sal
