# Architecture

## Principles

1. **Build heavy, serve light.** All the heavy GIS work (overlays, joins, scoring) runs once,
   offline, in Python. The public site is plain static files: no server, no database, no
   framework, no build step. A cheap phone on a slow connection gets one HTML page, ~10 KB of
   our JS/CSS, ~40 KB gzipped of Leaflet, and one pre-simplified data file.
2. **Object-oriented and small.** Each concern is a class with one job, and the pieces can be swapped.
3. **Reproducible.** `wotl build` goes from raw files to every output in one go. Settings live in
   `config/pipeline.toml`, dependencies are pinned in `uv.lock`, and raw inputs are checksummed.
4. **Private by construction.** Personal fields cannot pass the clean stage.

## Pipeline

```
Context (config + named tables)
   │
   ├─ IngestStage / SampleIngestStage   ArcGIS layers + manual files → data/raw/<id>/, manifest.json, sources.md
   │                                    Census2011Builder: SuperWEB2 exports → canonical counts per small area
   ├─ CleanStage        CRS → EPSG:4326, make_valid, harmonise codes and names
   │                    OwnerTypeResolver: owner list → Surveyor-General public land → "Unknown"
   │                    PrivacyGuard.strip → data/processed/*.parquet
   ├─ JoinStage         census ⨝ small areas; ward + suburb via representative point; census place names
   ├─ IndexStage        Indicator (rate) → Normaliser (ZScore | MinMax) → DeprivationIndex (weighted, rank, quintile)
   ├─ OwnershipStage    OwnershipOverlay (hybrid): small parcels by point, large parcels cut exactly
   ├─ ReportStage       neighbourhood_profiles.csv, summary.md, pilot profile
   └─ MapStage          WebExporter: simplify (5 m) → round coords (1e-5°) → compact keys → data/areas.js
```

| Class | Module | Role |
|---|---|---|
| `PipelineConfig`, `IndicatorSpec`, `SourceSpec` | `config.py` | Immutable, typed config |
| `Stage`, `Pipeline`, `Context` | `pipeline.py` | Runs stages in order and times each one |
| `SourceLog` | `sources.py` | Provenance: checksums, dates, licences |
| `PrivacyGuard` | `privacy.py` | POPIA guard-rails and small-area suppression |
| `Census2011Builder`, `TableSpec`, `CountRule` | `census.py` | Reads SuperWEB2 cross-tab exports; category rules from config |
| `OwnerTypeResolver` | `clean.py` | Owner type per parcel in order of evidence; never assumes private |
| `OwnerTypeClassifier` | `clean.py` | Regex rules from config, run once per unique owner name |
| `ArcGISLayerFetcher` | `ingest.py` | Paged ArcGIS REST downloads into raw GeoJSON |
| `Normaliser` → `ZScore`, `MinMax` | `index.py` | Strategy pattern |
| `DeprivationIndex`, `Indicator` | `index.py` | The composite score |
| `OwnershipOverlay` | `ownership.py` | Hybrid area-by-owner-type: point assignment for erven, exact cut for parcels ≥ 2 ha |
| `WebExporter` | `map.py` | Builds the lightweight data file for the map |

Spatial overlays (`geopandas.overlay`, `sjoin`) use an STRtree spatial index. Area maths uses
EPSG:2048 (Lo19, metres). Intermediate files are GeoParquet, which is columnar, compressed and fast to reload.

## Front end

`web/app.js` is plain JS organised as small classes: `Palette`, `Legend`, `DetailPanel` and `MapView`.
- Leaflet's **canvas renderer** draws thousands of polygons without creating thousands of DOM nodes.
- The data ships as `window.WOTL = {...}` in a `<script>`, so the map opens from `file://` and
  from any static host (GitHub Pages, Netlify, an S3 bucket, a USB stick).
- The OSM basemap is optional context. If it can't load, the map still works.
- The layout is responsive (side panel on desktop, bottom panel on phones), has a dark mode, and
  uses no web fonts.

## Distribution

The `outputs/` folder **is** the app. Zip it, host it, or hand it out on a stick.
For the city-wide data (~5,000+ SALs), expect `areas.js` around 1–2 MB, or roughly 300–600 KB
gzipped by any static host.

## Roadmap

1. **Confirm sources.** Fill in URLs and licences in `config/pipeline.toml`, download the real data, and map
   Stats SA column names in `[census.column_map]`. Check the column aliases in `clean.py` against the real layers.
2. **First real build.** Check SAL code matching rates, the suppression count and the overlay sanity checks.
3. **Front-end polish.** Plain-language explainer, "compare to city" view, shareable URL per area
   (`#sal=…`), print-friendly area profile.
4. **Scale-up options if needed:** split `areas.js` per ward and load on demand; switch to
   FlatGeobuf/PMTiles; use DuckDB-spatial for national-scale joins.
5. **Beyond Cape Town:** the stages are city-agnostic. New municipalities need only config and sources.
6. **CI:** GitHub Actions to run tests and `make sample` on every PR, and to publish `outputs/` to Pages.
