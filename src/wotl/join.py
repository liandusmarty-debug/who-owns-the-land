"""Join: census -> small-area polygons, then attach ward, suburb and place context."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from .pipeline import Context, Stage


def contains_point(points: gpd.GeoDataFrame, zones: gpd.GeoDataFrame, column: str) -> pd.Series:
    """Value of `column` for the zone containing each point (first match), indexed like `points`."""
    hit = gpd.sjoin(points, zones[[column, "geometry"]], predicate="within", how="left")
    return hit[~hit.index.duplicated()][column].reindex(points.index)


class JoinStage(Stage):
    name = "join"

    def __init__(self, settlement_min_share: float = 0.25) -> None:
        # a small area counts as "in" an informal settlement if this share of its area overlaps it
        self.settlement_min_share = settlement_min_share

    def run(self, ctx: Context) -> None:
        cfg = ctx.config
        sal: gpd.GeoDataFrame = ctx["sal_boundaries"].merge(ctx["census"], on=cfg.census_key, how="left")
        unmatched = int(sal["households"].isna().sum())
        if unmatched:
            ctx.tables.setdefault("caveats", []).append(
                f"{unmatched} small areas had no matching census record and are shown without figures."
            )
        for col in ("place", "main_place"):
            if col not in sal:
                sal[col] = pd.NA

        metric = sal.to_crs(cfg.metric_crs)
        sal["area_km2"] = (metric.area / 1e6).astype("float32")

        # ward and suburb: the zone containing each small area's representative point (cheap, robust)
        pts = gpd.GeoDataFrame(geometry=metric.representative_point(), crs=cfg.metric_crs, index=sal.index)
        sal["ward_id"] = contains_point(pts, ctx["wards"].to_crs(cfg.metric_crs), "ward_id")
        sal["suburb"] = (
            contains_point(pts, ctx["suburbs"].to_crs(cfg.metric_crs), "suburb") if "suburbs" in ctx.tables else pd.NA
        )

        sal["settlement"] = pd.NA
        if "informal_settlements" in ctx.tables:
            sal["settlement"] = self._settlements(metric, ctx["informal_settlements"].to_crs(cfg.metric_crs))

        sal["in_pilot"] = sal["place"].fillna("").str.contains(cfg.pilot_name, case=False, regex=False) | sal[
            "settlement"
        ].fillna("").str.contains(cfg.pilot_name, case=False, regex=False)
        ctx["areas"] = sal

    def _settlements(self, metric: gpd.GeoDataFrame, stl: gpd.GeoDataFrame) -> pd.Series:
        """Largest-overlap informal settlement name per small area, above the share threshold."""
        ov = gpd.overlay(
            metric[["sal_code", "geometry"]], stl[["name", "geometry"]], how="intersection", keep_geom_type=True
        )
        if ov.empty:
            return pd.Series(pd.NA, index=metric.index)
        ov["a"] = ov.area
        ov = ov.sort_values("a", ascending=False).drop_duplicates("sal_code").set_index("sal_code")
        share = ov["a"] / metric.set_index("sal_code").area.reindex(ov.index)
        names = ov["name"].where(share >= self.settlement_min_share)
        return metric["sal_code"].map(names)
