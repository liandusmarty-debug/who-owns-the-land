# Who Owns the Land?

A non-profit, open data project that profiles **neighbourhoods (never individuals)** in the
City of Cape Town: how deprived each area is, and who owns the land underneath it.
It supports the Masiphumelele housing pilot.

## Quick start

```bash
# 1. install uv once (https://docs.astral.sh/uv/), then:
make setup          # creates .venv with pinned dependencies (uv.lock)
make sample         # full pipeline on a synthetic city -> outputs/_sample/
make test
```

Open `outputs/_sample/map.html` straight from disk. No server is needed.

With real data in `data/raw/<source-id>/` (see `config/pipeline.toml` → `[[sources]]`):

```bash
make build          # == uv run wotl build  -> outputs/
```

## What gets produced

| File | What it is |
|---|---|
| `outputs/neighbourhood_profiles.csv` | One row per small area: indicators, index, rank, quintile, ownership mix |
| `outputs/map.html` (+ `data/areas.js`, `app.js`, `vendor/`) | Static interactive map. Copy the folder anywhere (web host, USB stick) |
| `outputs/summary.md` | Top 20 most deprived areas, ownership breakdown, caveats |
| `outputs/profile_masiphumelele.md` | One-page pilot profile |
| `sources.md` | Generated log of every dataset: publisher, licence, retrieval date, checksum |

## Hard rules (enforced in code)

- **Area-level only (POPIA).** `PrivacyGuard` strips personal columns at the clean stage and
  refuses to write any output that still contains one. Owner names are turned into an owner
  *type* (City / Province / National / Private / Other) and then discarded.
- Areas below `min_households` are suppressed and left out of the ranking.
- `data/raw/` is never modified. Every transformation is in `src/wotl/`.
- Outputs use neutral wording.

## Layout

```
config/pipeline.toml   all tunables: weights, thresholds, CRS, owner rules, sources
src/wotl/              the pipeline (one module per stage, see docs/ARCHITECTURE.md)
web/                   static front end (vanilla JS + vendored Leaflet), copied into outputs/
tests/                 unit tests + an end-to-end synthetic build
data/raw|processed/    git-ignored; rebuilt from sources
notebooks/             exploration only; core logic lives in src/
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and roadmap.
