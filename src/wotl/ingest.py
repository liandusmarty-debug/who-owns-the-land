"""Ingest: fetch raw sources into data/raw/<id>/ (never modified afterwards) and load them.

Two interchangeable stages:
  * IngestStage        — real data: downloads where a URL is configured, otherwise
                         expects the file to be dropped into data/raw/<id>/ by hand.
  * SampleIngestStage  — generates a synthetic, clearly-fake city so the whole
                         pipeline and web app can be developed before real data lands.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point, box

from .config import SourceSpec
from .pipeline import Context, Stage
from .sources import SourceLog

log = logging.getLogger("wotl")

VECTOR_EXT = (".gpkg", ".parquet", ".geojson", ".shp", ".fgb")
TABLE_EXT = (".csv", ".parquet", ".xlsx")
VECTOR_SOURCES = ("sal_boundaries", "wards", "informal_settlements", "parcels")


def _find(folder: Path, exts: tuple[str, ...]) -> Path:
    for ext in exts:
        hits = sorted(folder.rglob(f"*{ext}"))
        if hits:
            return hits[0]
    raise FileNotFoundError(
        f"No {exts} file in {folder}. Download it manually (see sources in config/pipeline.toml)."
    )


def read_vector(folder: Path) -> gpd.GeoDataFrame:
    path = _find(folder, VECTOR_EXT)
    return gpd.read_parquet(path) if path.suffix == ".parquet" else gpd.read_file(path, engine="pyogrio")


def read_table(folder: Path) -> pd.DataFrame:
    path = _find(folder, TABLE_EXT)
    if path.suffix == ".csv":
        return pd.read_csv(path, dtype=str)  # typed in the clean stage; keeps SAL codes intact
    if path.suffix == ".xlsx":
        return pd.read_excel(path)
    return pd.read_parquet(path)


class Downloader:
    def __init__(self, timeout: int = 120) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "who-owns-the-land-pipeline/0.1"
        self.timeout = timeout

    def fetch(self, spec: SourceSpec, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        if any(folder.iterdir()):
            return  # raw data is immutable: never re-download over it
        if not spec.url:
            log.warning("source %s has no URL — place its file in %s", spec.id, folder)
            return
        name = spec.url.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or f"{spec.id}.bin"
        log.info("downloading %s", spec.url)
        with self.session.get(spec.url, stream=True, timeout=self.timeout) as r:
            r.raise_for_status()
            tmp = folder / (name + ".part")
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            tmp.rename(folder / name)


class IngestStage(Stage):
    name = "ingest"

    def __init__(self, raw_dir: Path | None = None) -> None:
        self.raw_dir = raw_dir

    def run(self, ctx: Context) -> None:
        raw = self.raw_dir or ctx.config.paths.raw
        srclog = SourceLog(raw)
        downloader = Downloader()
        for spec in ctx.config.sources:
            folder = raw / spec.id
            downloader.fetch(spec, folder)
            if folder.exists() and any(folder.iterdir()):
                srclog.record(spec, folder)
        srclog.save()
        md = srclog.render_markdown()
        if ctx.sample_mode:
            md = ("> **SYNTHETIC SAMPLE DATA — not real. "
                  "Metadata below describes the real sources it stands in for.**\n\n") + md
        md_path = raw / "sources.md" if ctx.sample_mode else ctx.config.paths.root / "sources.md"
        md_path.write_text(md, encoding="utf-8")

        ctx["census_raw"] = read_table(raw / "census_sal")
        for sid in VECTOR_SOURCES:
            ctx[f"{sid}_raw"] = read_vector(raw / sid)


class SampleCityGenerator:
    """Deterministic synthetic city laid over the far-south peninsula. ALL VALUES ARE FAKE."""

    UTM = "EPSG:32734"
    ORIGIN = Point(18.384, -34.128)  # roughly Masiphumelele, used only to place the grid

    def __init__(self, n: int = 24, cell_m: float = 250.0, seed: int = 2022) -> None:
        self.n, self.cell, self.rng = n, cell_m, np.random.default_rng(seed)

    def write(self, root: Path) -> None:
        ox, oy = gpd.GeoSeries([self.ORIGIN], crs="EPSG:4326").to_crs(self.UTM).iloc[0].coords[0]
        half = self.n * self.cell / 2
        x0, y0 = ox - half, oy - half

        cells, codes, deprivation = [], [], []
        hotspots = [(0.45, 0.5, 0.18), (0.8, 0.2, 0.12), (0.15, 0.85, 0.1)]
        for i in range(self.n):
            for j in range(self.n):
                cells.append(box(x0 + i * self.cell, y0 + j * self.cell,
                                 x0 + (i + 1) * self.cell, y0 + (j + 1) * self.cell))
                codes.append(f"1990{i:03d}{j:03d}")
                u, v = (i + 0.5) / self.n, (j + 0.5) / self.n
                d = max(np.exp(-((u - a) ** 2 + (v - b) ** 2) / (2 * s * s)) for a, b, s in hotspots)
                deprivation.append(np.clip(d + self.rng.normal(0, 0.08), 0, 1))
        dep = np.array(deprivation)

        sal = gpd.GeoDataFrame({"sal_code": codes}, geometry=cells, crs=self.UTM)
        hh = self.rng.poisson(110 + 140 * dep)
        hh[self.rng.choice(len(hh), 12, replace=False)] = self.rng.integers(3, 25, 12)  # tiny areas
        pop = (hh * self.rng.uniform(2.6, 3.8, len(hh))).astype(int)

        def share(lo: float, hi: float) -> np.ndarray:
            return self.rng.binomial(hh, np.clip(lo + (hi - lo) * dep, 0, 1))

        lf = (pop * 0.45).astype(int)
        adults = (pop * 0.62).astype(int)
        census = pd.DataFrame({
            "sal_code": codes, "population": pop, "households": hh,
            "hh_informal": share(0.01, 0.85), "hh_no_piped_water": share(0.0, 0.55),
            "hh_no_flush_toilet": share(0.01, 0.6), "hh_no_electric_light": share(0.0, 0.3),
            "hh_low_income": share(0.1, 0.8),
            "labour_force": lf, "unemployed": self.rng.binomial(lf, np.clip(0.08 + 0.45 * dep, 0, 1)),
            "adults_20plus": adults, "adults_no_matric": self.rng.binomial(adults, np.clip(0.2 + 0.5 * dep, 0, 1)),
        })

        k = 4  # wards = 4x4 blocks of SALs
        wards = sal.assign(
            ward_id=[f"Ward {100 + (i // k) * (self.n // k) + (j // k)}" for i in range(self.n) for j in range(self.n)]
        ).dissolve("ward_id").reset_index()[["ward_id", "geometry"]]

        def blob(cx: float, cy: float, r: float) -> object:
            return Point(x0 + cx * 2 * half, y0 + cy * 2 * half).buffer(r * 2 * half, quad_segs=6)

        settlements = gpd.GeoDataFrame(
            {"name": ["Masiphumelele", "Sample Settlement B", "Sample Settlement C"]},
            geometry=[blob(0.45, 0.5, 0.11), blob(0.8, 0.2, 0.07), blob(0.15, 0.85, 0.06)],
            crs=self.UTM,
        )

        owners = ["CITY OF CAPE TOWN", "WESTERN CAPE PROVINCIAL GOVERNMENT", "REPUBLIC OF SOUTH AFRICA",
                  "SAMPLE PERSON {n:04d}", "SAMPLE HOLDINGS (PTY) LTD", "SAMPLE FAMILY TRUST"]
        pc, pgeo, powner = 370.0, [], []
        m = int(2 * half // pc) + 1
        for i in range(m):
            for j in range(m):
                pgeo.append(box(x0 + i * pc, y0 + j * pc, x0 + (i + 1) * pc - 8, y0 + (j + 1) * pc - 8))
                o = self.rng.choice(len(owners), p=[0.3, 0.12, 0.1, 0.3, 0.12, 0.06])
                powner.append(owners[o].format(n=int(self.rng.integers(10000))))
        parcels = gpd.GeoDataFrame({"owner_name": powner}, geometry=pgeo, crs=self.UTM)

        out = {"sal_boundaries": sal, "wards": wards, "informal_settlements": settlements, "parcels": parcels}
        for sid, gdf in out.items():
            (root / sid).mkdir(parents=True, exist_ok=True)
            gdf.to_crs("EPSG:4326").to_file(root / sid / f"{sid}.gpkg", engine="pyogrio")
        (root / "census_sal").mkdir(parents=True, exist_ok=True)
        census.to_csv(root / "census_sal" / "census_sal.csv", index=False)


class SampleIngestStage(IngestStage):
    name = "ingest (synthetic sample)"

    def run(self, ctx: Context) -> None:
        root = ctx.config.paths.raw / "_sample"
        if not (root / "census_sal").exists():
            SampleCityGenerator().write(root)
        self.raw_dir = root
        super().run(ctx)
