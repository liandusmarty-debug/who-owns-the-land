"""Land ownership overlay: share of each area's land by owner type.

Hybrid method, so it runs city-wide (~850k parcels) on modest hardware without losing accuracy:
  * small parcels (the vast majority: ordinary erven) are assigned whole to the small area that
    contains their representative point — small areas largely follow erf boundaries;
  * large parcels (farms, wetlands, reserves, big state holdings), which often straddle several
    small areas, are intersected exactly with the small-area polygons.
Land not covered by any parcel (mostly roads and unregistered land) is reported as "Unmapped".
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from .pipeline import Context, Stage

UNMAPPED = "Unmapped"


class OwnershipOverlay:
    def __init__(
        self,
        parcels: gpd.GeoDataFrame,
        categories: tuple[str, ...],
        metric_crs: str,
        exact_min_m2: float = 20_000,
    ) -> None:
        p = parcels.to_crs(metric_crs)[["owner_type", "geometry"]].copy()
        p["owner_type"] = p["owner_type"].astype(str)
        area = p.area
        big = area >= exact_min_m2
        self.large = p[big]
        small = p[~big]
        self.small = gpd.GeoDataFrame(
            {"owner_type": small["owner_type"], "a": area[~big].to_numpy()},
            geometry=small.representative_point(),
            crs=metric_crs,
        )
        self.categories = categories
        self.metric_crs = metric_crs

    @staticmethod
    def column(category: str) -> str:
        return f"own_{category.lower()}_pct"

    @property
    def columns(self) -> list[str]:
        return [self.column(c) for c in (*self.categories, UNMAPPED)]

    def shares(self, zones: gpd.GeoDataFrame, key: str) -> pd.DataFrame:
        """% of each zone's area by owner type, plus an Unmapped remainder and the dominant type."""
        z = zones.to_crs(self.metric_crs)[[key, "geometry"]]
        total = z.set_index(key).area
        parts = [gpd.sjoin(self.small, z, predicate="within", how="inner")[[key, "owner_type", "a"]]]
        if not self.large.empty:
            cut = gpd.overlay(z, self.large, how="intersection", keep_geom_type=True)
            parts.append(cut.assign(a=cut.area)[[key, "owner_type", "a"]])
        hit = pd.concat(parts, ignore_index=True)
        piv = (
            hit.pivot_table(index=key, columns="owner_type", values="a", aggfunc="sum")
            .reindex(index=total.index, columns=list(self.categories))
            .fillna(0.0)
        )
        pct = piv.div(total, axis=0) * 100
        over = pct.sum(axis=1)  # parcels straddling an edge can push the sum slightly past 100%
        pct = pct.div(over.where(over > 100, 100), axis=0) * 100
        pct[UNMAPPED] = (100 - pct.sum(axis=1)).clip(lower=0)
        cats = list(self.categories)
        dominant = pct[cats].idxmax(axis=1).where(pct[cats].max(axis=1) > 0)
        pct.columns = self.columns
        pct = pct.astype(float).round(1)
        pct["dominant_owner"] = dominant
        return pct


class OwnershipStage(Stage):
    name = "ownership overlay"

    def run(self, ctx: Context) -> None:
        cfg = ctx.config
        overlay = OwnershipOverlay(ctx["parcels"], cfg.owner_categories, cfg.metric_crs)
        areas = ctx["areas"]
        ctx["areas"] = areas.join(overlay.shares(areas, "sal_code"), on="sal_code")
        ctx["ownership_columns"] = overlay.columns

        pilot = areas[areas["in_pilot"]]
        if not pilot.empty:
            zone = pilot.dissolve().assign(zone=cfg.pilot_name)[["zone", "geometry"]]
            ctx["pilot_ownership"] = overlay.shares(zone, "zone").iloc[0]
