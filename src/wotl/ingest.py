"""Ingest: fetch raw sources into data/raw/<id>/ (never modified afterwards) and load them.

Two interchangeable stages:
  * IngestStage        — real data: downloads where a URL is configured, otherwise
                         expects the file to be dropped into data/raw/<id>/ by hand.
  * SampleIngestStage  — generates a synthetic, clearly-fake city so the whole
                         pipeline and web app can be developed before real data lands.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point, box

from .census import Census2011Builder
from .config import SourceSpec
from .pipeline import Context, Stage
from .sources import SourceLog

log = logging.getLogger("wotl")

VECTOR_EXT = (".gpkg", ".parquet", ".geojson", ".shp", ".fgb")
TABLE_EXT = (".csv", ".parquet", ".xlsx")
REQUIRED_VECTORS = ("sal_boundaries", "wards", "parcels")
OPTIONAL_VECTORS = ("suburbs", "informal_settlements", "sg_public_places", "sg_streets", "sg_state_land")


def _find(folder: Path, exts: tuple[str, ...]) -> Path:
    for ext in exts:
        hits = sorted(folder.rglob(f"*{ext}"))
        if hits:
            return hits[0]
    raise FileNotFoundError(f"No {exts} file in {folder}. Download it manually (see sources in config/pipeline.toml).")


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


class ArcGISLayerFetcher:
    """Downloads every feature of one ArcGIS REST layer as GeoJSON, paging past maxRecordCount."""

    def __init__(self, session: requests.Session, timeout: int = 120) -> None:
        self.session, self.timeout = session, timeout

    def _get(self, url: str, params: dict) -> dict:
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"{url}: {data['error'].get('message')} {data['error'].get('details', '')}")
        return data

    def query_params(self, spec: SourceSpec) -> dict:
        params = {"where": spec.where, "outFields": spec.out_fields, "outSR": 4326, "f": "geojson"}
        if spec.bbox:
            xmin, ymin, xmax, ymax = spec.bbox
            params |= {
                "geometry": f"{xmin},{ymin},{xmax},{ymax}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
            }
        return params

    def fetch(self, spec: SourceSpec, out: Path) -> int:
        layer = spec.url.rstrip("/")
        meta = self._get(layer, {"f": "json"})
        page = int(meta.get("maxRecordCount") or 1000)
        params = self.query_params(spec)
        features: list[dict] = []
        offset = 0
        while True:
            batch = self._get(f"{layer}/query", params | {"resultOffset": offset, "resultRecordCount": page})
            feats = batch.get("features", [])
            features.extend(feats)
            log.info("  %s: %d features", spec.id, len(features))
            if not feats or not (
                batch.get("exceededTransferLimit")
                or batch.get("properties", {}).get("exceededTransferLimit")
                or len(feats) == page
            ):
                break
            offset += len(feats)
        tmp = out.with_suffix(".part")
        tmp.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
        tmp.rename(out)
        (out.parent / "query.json").write_text(
            json.dumps(
                {
                    "layer": layer,
                    "params": params,
                    "layer_name": meta.get("name"),
                    "copyright": meta.get("copyrightText"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return len(features)


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
        if spec.kind == "arcgis":
            log.info("querying ArcGIS layer %s", spec.url)
            ArcGISLayerFetcher(self.session, self.timeout).fetch(spec, folder / f"{spec.id}.geojson")
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
        downloader = None if ctx.sample_mode else Downloader()  # sample mode never touches the network
        for spec in ctx.config.sources:
            folder = raw / spec.id
            if downloader:
                downloader.fetch(spec, folder)
            if folder.exists() and any(folder.iterdir()):
                srclog.record(spec, folder)
        srclog.save()
        md = srclog.render_markdown()
        if ctx.sample_mode:
            md = (
                "> **SYNTHETIC SAMPLE DATA — not real. "
                "Metadata below describes the real sources it stands in for.**\n\n"
            ) + md
        md_path = raw / "sources.md" if ctx.sample_mode else ctx.config.paths.root / "sources.md"
        md_path.write_text(md, encoding="utf-8")

        cfg = ctx.config
        ctx["census"] = Census2011Builder(cfg.census_tables, cfg.census_exclude).build(raw / "census_sal")
        for sid in REQUIRED_VECTORS:
            ctx[f"{sid}_raw"] = read_vector(raw / sid)
        for sid in OPTIONAL_VECTORS:
            folder = raw / sid
            if folder.exists() and any(folder.glob("*")):
                ctx[f"{sid}_raw"] = read_vector(folder)
            else:
                log.info("  optional source %s not present — skipped", sid)
        ot = raw / "owner_types"
        ctx["owner_types_raw"] = read_table(ot) if ot.exists() and any(ot.glob("*.csv")) else None


# Census 2011 answer categories (as labelled by Stats SA) used by the synthetic exports.
# Each table: (title, counting unit, "bad" categories, "good" categories).
CENSUS_2011_LABELS: dict[str, tuple[str, str, list[str], list[str]]] = {
    "dwelling_type": (
        "Type of main dwelling",
        "Households",
        [
            "Informal dwelling (shack; in backyard)",
            "Informal dwelling (shack; not in backyard; e.g. in an informal/squatter settlement or on a farm)",
        ],
        [
            "House or brick/concrete block structure on a separate stand or yard or on a farm",
            "Flat or apartment in a block of flats",
            "Townhouse (semi-detached house in a complex)",
            "House/flat/room in backyard",
            "Room/flatlet on a property or larger dwelling/servants quarters/granny flat",
        ],
    ),
    "piped_water": (
        "Piped water",
        "Households",
        [
            "Piped (tap) water on community stand: distance less than 200m from dwelling/institution",
            "Piped (tap) water on community stand: distance between 200m and 500m from dwelling/institution",
            "No access to piped (tap) water",
        ],
        ["Piped (tap) water inside dwelling/institution", "Piped (tap) water inside yard"],
    ),
    "toilet_facilities": (
        "Toilet facilities",
        "Households",
        ["None", "Chemical toilet", "Pit toilet without ventilation", "Bucket toilet", "Other"],
        ["Flush toilet (connected to sewerage system)", "Flush toilet (with septic tank)"],
    ),
    "energy_lighting": (
        "Energy or fuel for lighting",
        "Households",
        ["Gas", "Paraffin", "Candles (not a valid option)", "Solar", "None"],
        ["Electricity"],
    ),
    "household_income": (
        "Annual household income",
        "Households",
        ["No income", "R 1 - R 4800", "R 4801 - R 9600", "R 9601 - R 19 600", "R 19 601 - R 38 200"],
        [
            "R 38 201 - R 76 400",
            "R 76 401 - R 153 800",
            "R 153 801 - R 307 600",
            "R 307 601 - R 614 400",
            "R 614 001 - R 1 228 800",
            "R 1 228 801 - R 2 457 600",
            "R 2 457 601 or more",
        ],
    ),
    "education_20plus": (
        "Highest educational level (persons aged 20+)",
        "Persons",
        [
            "No schooling",
            "Grade 0",
            "Grade 1 / Sub A",
            "Grade 3 / Std 1/ABET 1Kha Ri Gude;SANLI",
            "Grade 7 / Std 5/ ABET 3",
            "Grade 10 / Std 8 / Form 3",
            "Grade 11 / Std 9 / Form 4",
            "Certificate with less than Grade 12 / Std 10",
        ],
        [
            "Grade 12 / Std 10 / Form 5",
            "Certificate with Grade 12 / Std 10",
            "Diploma with Grade 12 / Std 10",
            "Bachelors Degree",
            "Higher Degree Masters / PhD",
        ],
    ),
}


class SampleCityGenerator:
    """Deterministic synthetic city laid over the far-south peninsula. ALL VALUES ARE FAKE.

    Every file mirrors the format of its real counterpart (see docs/DATA-SOURCES.md), so sample
    builds exercise the same code paths as real ones: SuperWEB2-style census CSVs, ArcGIS-style
    layers with the real field names, parcels without owners, Surveyor-General public land, and a
    partial owner-types list.
    """

    UTM = "EPSG:32734"
    ORIGIN = Point(18.384, -34.128)  # roughly Masiphumelele, used only to place the grid
    HOTSPOTS = [  # (u, v, spread, sub-place, main place)
        (0.45, 0.5, 0.18, "Masiphumelele", "Noordhoek"),
        (0.8, 0.2, 0.12, "Sample Place B", "Sample Town"),
        (0.15, 0.85, 0.1, "Sample Place C", "Sample Town"),
    ]

    def __init__(self, n: int = 24, cell_m: float = 250.0, seed: int = 2011) -> None:
        self.n, self.cell, self.rng = n, cell_m, np.random.default_rng(seed)

    # -- helpers ------------------------------------------------------------------
    def _split(self, total: np.ndarray, p_bad: np.ndarray, bad: list[str], good: list[str]) -> pd.DataFrame:
        n_bad = self.rng.binomial(total, np.clip(p_bad, 0, 1))
        cols = {}
        for labels, counts in ((bad, n_bad), (good, total - n_bad)):
            w = self.rng.dirichlet(np.ones(len(labels)) * 3)
            split = np.array([self.rng.multinomial(c, w) for c in counts])
            cols |= {lab: split[:, k] for k, lab in enumerate(labels)}
        return pd.DataFrame(cols)

    @staticmethod
    def _write_superweb(path: Path, title: str, unit: str, codes: list[str], table: pd.DataFrame) -> None:
        table = table.assign(Total=table.sum(axis=1))
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, quoting=csv.QUOTE_ALL)
            w.writerow(["Census 2011 (SYNTHETIC SAMPLE - not real data)"])
            w.writerow([f"{title} by Small Area"])
            w.writerow([f"Counting: {unit}"])
            w.writerow([])
            w.writerow(["Small Area", *table.columns, ""])
            for code, row in zip(codes, table.itertuples(index=False), strict=True):
                w.writerow([code, *row, ""])
            w.writerow([])
            w.writerow(["Data Source: synthetic sample generated by wotl"])

    # -- main ---------------------------------------------------------------------
    def write(self, root: Path) -> None:
        ox, oy = gpd.GeoSeries([self.ORIGIN], crs="EPSG:4326").to_crs(self.UTM).iloc[0].coords[0]
        half = self.n * self.cell / 2
        x0, y0 = ox - half, oy - half

        cells, codes, dep, sp, mp = [], [], [], [], []
        for i in range(self.n):
            for j in range(self.n):
                cells.append(
                    box(x0 + i * self.cell, y0 + j * self.cell, x0 + (i + 1) * self.cell, y0 + (j + 1) * self.cell)
                )
                codes.append(f"199{i * self.n + j + 1:04d}")
                u, v = (i + 0.5) / self.n, (j + 0.5) / self.n
                near = [
                    (np.exp(-((u - a) ** 2 + (b - v) ** 2) / (2 * s * s)), name, town)
                    for a, b, s, name, town in self.HOTSPOTS
                ]
                d, name, town = max(near)
                dep.append(np.clip(d + self.rng.normal(0, 0.08), 0, 1))
                if d > 0.6:
                    sp.append(name if (i + j) % 9 else f"{name} School Site Informal")
                    mp.append(town)
                else:
                    sp.append(f"Sample Suburb {1 + (i // 6) * 4 + j // 6}")
                    mp.append("Sample Town")
        dep = np.array(dep)

        sal = gpd.GeoDataFrame({"SAL_CODE": codes, "SP_NAME": sp, "MP_NAME": mp}, geometry=cells, crs=self.UTM)

        # --- census: SuperWEB2-style exports ---
        hh = self.rng.poisson(110 + 140 * dep)
        hh[self.rng.choice(len(hh), 12, replace=False)] = self.rng.integers(3, 25, 12)  # tiny areas
        persons = (hh * self.rng.uniform(2.6, 3.8, len(hh))).astype(int)
        adults = (persons * 0.62).astype(int)
        census_dir = root / "census_sal"
        census_dir.mkdir(parents=True, exist_ok=True)
        ranges = {
            "dwelling_type": (0.01, 0.85),
            "piped_water": (0.0, 0.55),
            "toilet_facilities": (0.01, 0.6),
            "energy_lighting": (0.0, 0.3),
            "household_income": (0.15, 0.8),
            "education_20plus": (0.2, 0.7),
        }
        for key, (title, unit, bad, good) in CENSUS_2011_LABELS.items():
            lo, hi = ranges[key]
            base = adults if unit == "Persons" else hh
            table = self._split(base, lo + (hi - lo) * dep, bad, good)
            table["Unspecified"] = self.rng.binomial(base, 0.01)
            self._write_superweb(census_dir / f"{key}.csv", title, unit, codes, table)
        under15 = self.rng.binomial(persons, 0.25)
        working = persons - under15
        lf = self.rng.binomial(working, 0.6)
        unemployed = self.rng.binomial(lf, np.clip(0.08 + 0.45 * dep, 0, 1))
        discouraged = self.rng.binomial(working - lf, 0.08)
        emp = pd.DataFrame(
            {
                "Employed": lf - unemployed,
                "Unemployed": unemployed,
                "Discouraged work-seeker": discouraged,
                "Other not economically active": working - lf - discouraged,
                "Age less than 15 years": under15,
                "Not applicable": np.zeros_like(persons),
            }
        )
        self._write_superweb(census_dir / "employment_status.csv", "Official employment status", "Persons", codes, emp)

        # --- boundaries with real field names ---
        k = 4
        ward_no = [61 + (i // k) * (self.n // k) + (j // k) for i in range(self.n) for j in range(self.n)]
        wards = (
            sal.assign(WARD_NAME=[str(w) for w in ward_no])
            .dissolve("WARD_NAME")
            .reset_index()[["WARD_NAME", "geometry"]]
            .assign(WARD_YEAR=2026)
        )
        suburbs = (
            sal.assign(OFC_SBRB_NAME=[s.upper() for s in sal["SP_NAME"].str.replace(" School Site Informal", "")])
            .dissolve("OFC_SBRB_NAME")
            .reset_index()[["OFC_SBRB_NAME", "geometry"]]
        )

        # --- parcels: no owner field, like the City's Land Parcels layer ---
        pc, pgeo, sg26, truth = 370.0, [], [], []
        m = int(2 * half // pc) + 1
        types = ["City", "Province", "National", "Private", "Other"]
        for i in range(m):
            for j in range(m):
                pgeo.append(box(x0 + i * pc, y0 + j * pc, x0 + (i + 1) * pc - 8, y0 + (j + 1) * pc - 8))
                sg26.append(f"C0160038{i:05d}{j:05d}00000000")
                truth.append(types[self.rng.choice(5, p=[0.3, 0.12, 0.1, 0.38, 0.1])])
        parcels = gpd.GeoDataFrame(
            {
                "SG26_CODE": sg26,
                "PRTY_NMBR": [str(1000 + k) for k in range(len(sg26))],
                "LU_LGL_STS_DSCR": "Registered",
                "ZONING": "Single Residential 1 : Conventional Housing",
            },
            geometry=pgeo,
            crs=self.UTM,
        )
        truth = np.array(truth)

        # --- Surveyor-General public land: some City and National parcels ---
        idx = np.arange(len(parcels))
        city_idx = self.rng.choice(idx[truth == "City"], 20, replace=False)
        nat_idx = self.rng.choice(idx[truth == "National"], 6, replace=False)
        sg_public = gpd.GeoDataFrame(
            {"PRCL_KEY": city_idx, "PRCL_TYPE": "Public Place"},
            geometry=parcels.geometry.iloc[city_idx].buffer(1).values,
            crs=self.UTM,
        )
        sg_state = gpd.GeoDataFrame(
            {"PRCL_KEY": nat_idx, "PRCL_TYPE": "Unalienated State Land"},
            geometry=parcels.geometry.iloc[nat_idx].buffer(1).values,
            crs=self.UTM,
        )

        # --- owner_types: partial, like responses to data requests (types, plus a few raw names) ---
        known = self.rng.choice(
            np.setdiff1d(idx, np.concatenate([city_idx, nat_idx])), int(len(idx) * 0.45), replace=False
        )
        names = {
            "City": "CITY OF CAPE TOWN",
            "Province": "WESTERN CAPE PROVINCIAL GOVERNMENT",
            "National": "REPUBLIC OF SOUTH AFRICA",
            "Other": "SAMPLE FAMILY TRUST",
        }
        rows = []
        for n_, k_ in enumerate(known):
            t = truth[k_]
            if n_ % 4 == 0:  # raw name -> classified, then dropped
                rows.append(
                    {
                        "sg26_code": sg26[k_],
                        "owner_type": "",
                        "owner_name": names.get(t, f"SAMPLE PERSON {n_:04d}"),
                        "source": "sample deeds",
                    }
                )
            else:
                rows.append({"sg26_code": sg26[k_], "owner_type": t, "owner_name": "", "source": "sample request"})
        (root / "owner_types").mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(root / "owner_types" / "owner_types.csv", index=False)

        layers = {
            "sal_boundaries": sal,
            "wards": wards,
            "suburbs": suburbs,
            "parcels": parcels,
            "sg_public_places": sg_public,
            "sg_state_land": sg_state,
        }
        for sid, gdf in layers.items():
            (root / sid).mkdir(parents=True, exist_ok=True)
            gdf.to_crs("EPSG:4326").to_file(root / sid / f"{sid}.geojson", engine="pyogrio")


class SampleIngestStage(IngestStage):
    name = "ingest (synthetic sample)"

    def run(self, ctx: Context) -> None:
        root = ctx.config.paths.raw / "_sample"
        if not (root / "census_sal" / "dwelling_type.csv").exists():
            SampleCityGenerator().write(root)
        self.raw_dir = root
        super().run(ctx)
