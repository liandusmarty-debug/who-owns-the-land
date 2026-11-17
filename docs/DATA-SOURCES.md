# Data sources: research findings

*Researched 17 November 2026. Every endpoint below was queried live from the project environment
unless marked otherwise.*

## Summary

| Need | Source chosen | Status |
|---|---|---|
| Living conditions (7 indicators) | **Census 2011** small-area tables, Stats SA SuperWEB2 | ⚠️ Manual export (free registration) |
| Small-area boundaries | Census 2011 Small Areas, Western Cape spatial data warehouse | ✅ Open ArcGIS API, 5,339 areas in Cape Town |
| Wards | City of Cape Town, 2026 wards (118) | ✅ Open ArcGIS API |
| Readable place names | Census sub-place / main-place names; City *Official Suburbs* (778) | ✅ Open ArcGIS API |
| Land parcels and zoning | City of Cape Town *Land Parcels* (852,214 parcels) | ✅ Open ArcGIS API, **no owner field** |
| Known public land | Surveyor-General: Public Places, Streets Cadastre, Unalienated State Land | ✅ Open ArcGIS API |
| Owner *type* for remaining parcels | Formal requests and partners (see [requests](requests/)) | ⏳ Not yet available |
| Informal settlement boundaries | Provincial layer now **requires a login**; no open City layer found | ❌ Use census sub-places instead |
| Current population (context) | City *Population Estimates 2026 (Suburb level)* | ✅ Open ArcGIS API |

## Why Census 2011 and not Census 2022

The brief assumed Census 2022 small-area data. It isn't publicly available:

- After a quality assessment, Stats SA released sub-municipal Census 2022 results **only at ward
  level**, and the ward product (*Ward-level Small Area Population Estimates, 2022*, Nov 2025) covers
  only **age, sex and population group**. It has nothing on housing, services or work.
- Census 2022 Community Profiles (main place, sub-place and ward) have **not been released**.
- Small Area Layer data is "**available on request only**" from Stats SA (DataFirst).
- **Household income and employment were withheld nationally** because of reporting and coverage bias (Aug 2024).

**Census 2011** is the most recent census with all seven indicators at small-area level. The project
uses it as a **2011 baseline**, and every output says so. Areas have changed a lot since then: the
City's Spatial Trends report counts informal housing units rising from 169,330 (2016) to 283,379.

Sources: [Stats SA ward product](https://www.statssa.gov.za/?p=18967) ·
[Ward product technical note](https://www.statssa.gov.za/wp-content/uploads/2025/11/Ward-statistical-product-technical-note.pdf) ·
[DataFirst Census 2022 catalogue](https://www.datafirst.uct.ac.za/dataportal/index.php/catalog/982) ·
[DataFirst district profiles note](https://www.datafirst.uct.ac.za/dataportal/index.php/catalog/1131)

## Sources in detail

### 1. Census 2011 small-area tables (`census_sal`)
- **Where:** Stats SA SuperWEB2, <https://superweb.statssa.gov.za/webapi/>. Needs free registration and a manual export.
- **Tables needed** (Census 2011, household or person level, by Small Area, City of Cape Town only):
  type of main dwelling · source of water / piped water · toilet facilities · energy for lighting ·
  annual household income · official employment status (ages 15–64) · highest educational level (ages 20+).
- **Recipe:** see [Exporting Census 2011 from SuperWEB2](#exporting-census-2011-from-superweb2).
  Save the CSVs into `data/raw/census_sal/`.
- **Terms:** Stats SA material may be used and processed if **Stats SA is acknowledged as the
  original source**. Our analysis must be presented as independent processing, and reprocessed data
  **may not be sold** without permission.

### 2. Census 2011 small-area boundaries (`sal_boundaries`)
- **Where:** `https://gis.westerncape.gov.za/server2/rest/services/SpatialDataWarehouse/StatsSA_CensusBoundaries/MapServer/2`
- **Filter:** `MN_MDB_C = 'CPT'`, which gives **5,339 small areas**. Max 2,000 records per request; pagination supported.
- **Fields:** `SAL_CODE`, `SP_NAME` (sub-place, e.g. "Masiphumelele"), `MP_NAME` (main place, e.g. "Noordhoek"), municipality codes.
- **Masiphumelele:** 10 small areas, in sub-places *Masiphumelele* and *Masiphumelele School Site Informal* (main place Noordhoek).
- **Terms:** © Statistics South Africa. Same acknowledgement terms as above.

### 3. Wards (`wards`)
- **Where:** `https://citymaps.capetown.gov.za/agsext/rest/services/Theme_Based/Political_Administrative_Boundaries/MapServer/7`
- **Content:** **118 wards, `WARD_YEAR` = 2026.** The layer's description text still says "2016", but the data is current.
- **Fields:** `WARD_NAME`, `WARD_YEAR`.
- **Terms:** City of Cape Town and Municipal Demarcation Board.

### 4. Official suburbs (`suburbs`)
- **Where:** same service, layer 4. **778 suburbs**, field `OFC_SBRB_NAME`. Used for readable area names and search.

### 5. Land parcels (`parcels`)
- **Where:** `https://services6.arcgis.com/nyYfO9SxHU2ChQd9/arcgis/rest/services/Property/FeatureServer/0`
- **Content:** **852,214 parcels.** Max 2,000 records per request.
- **Fields:** `SG26_CODE` (national parcel ID), `PRTY_NMBR`, `OFC_SBRB_NAME`, `WARD_NAME`,
  `LU_LGL_STS_DSCR` (legal status), `ZONING`, address fields.
- **No owner field.** Owner type has to come from other layers and the requests below. Address
  fields aren't needed and won't be stored (POPIA: an address plus the property makes a household identifiable).

### 6. Zoning (`zoning`)
- **Where:** `https://services6.arcgis.com/nyYfO9SxHU2ChQd9/arcgis/rest/services/Zoning/FeatureServer`.
  Split zoning is also at `https://esapqa.capetown.gov.za/agsext/rest/services/Theme_Based/ODP_SPLIT_4/FeatureServer/1`.
- **Use:** groundwork for "what can be done with the land" (development rights per area).

### 7. Surveyor-General cadastre: known public land
- **Where:** `https://gis.westerncape.gov.za/server2/rest/services/SpatialDataWarehouse/SG_PlanningCadastre/MapServer`.
  Max 1,000 records per request. © Surveyor General, Cape Town.
- **Counts in the Cape Town bounding box:**

  | Layer | id | Features | Owner type assigned |
  |---|---|---|---|
  | Public Places | 7 | 9,225 | City (public open space vests in the municipality) |
  | Streets Cadastre | 14 | 43,011 | City (public road) |
  | Unalienated State Land | 11 | 245 | National (state) |
  | Unalienated River Beds | 10 | 14 | National (state) |

- The City's `Transport/MapServer/16` **Road Ownership** layer can split roads by authority (City, Province or SANRAL).

### 8. Population estimates 2026 by suburb (context only)
- **Where:** `https://services6.arcgis.com/nyYfO9SxHU2ChQd9/arcgis/rest/services/Population_Estimates_2026_(Suburb_Level)/FeatureServer`
- **Use:** shows current population beside the 2011 baseline, so readers can see how areas have grown. It's not used in the index.

### Not available openly
- **Informal settlement boundaries.** The Western Cape layer `CoCT_InformalSettlements` now returns
  "Token Required", and no open City layer was found in a scan of all 58 `citymaps` services. Census
  sub-places and the 2011 dwelling-type indicator cover this need.
- **Valuation roll owner data.** The City only offers per-property lookups. The open "Valuations Suburbs
  2018 and 2022" layer is suburb-level values, with no owners.
- **City land register.** The City refused Ndifuna Ukwazi's PAIA requests for its list of City-owned parcels.
- **Deeds Office.** No open bulk data. Commercial resellers (e.g. WinDeed, Lightstone) sell it per query or area.

## City of Cape Town licence

- The [Open Data terms of use](https://www.capetown.gov.za/General/Terms-of-use-open-data) are a
  disclaimer: the data is free and provided "as is", with **no restriction on reuse or redistribution**.
- The [Open Data Policy 27781 (2020)](https://www.capetown.gov.za/media/vg2plaql/open_data_policy.pdf),
  §7.5–7.7, says access is free with no registration, the terms "will conform with open data
  principles", and users may "contribute to or add value to City data".
- **Our practice:** credit "City of Cape Town Open Data Portal" on every output. There's no formal
  named licence, so we record the terms URL and retrieval date in `sources.md`.

## Ownership strategy (layered)

For each land parcel, the owner type is the first of these that applies:

1. `owner_types.csv`: owner type by `SG26_CODE`, filled from the City's response, the People's Land Map
   (with Ndifuna Ukwazi's permission) and Deeds data for the Masiphumelele pilot. **Types only, never names.**
2. Surveyor-General Public Places or Streets → City. Unalienated State Land → National.
3. Otherwise **"Not yet known"**. It is never assumed to be private.

## Exporting Census 2011 from SuperWEB2

1. Register (free) at <https://superweb.statssa.gov.za/webapi/> and sign in.
2. Open **Census 2011**, then the **Household** dataset (or **Person** for employment and education).
3. Rows: **Geography → Small Area**, filtered to *Western Cape → City of Cape Town* (all small areas).
4. Columns: the variable, e.g. *Type of main dwelling*. Add all categories.
5. Export as **CSV (comma-separated)**. Name each file after its table, e.g. `dwelling_type.csv`.
6. Repeat for each table listed in section 1, then put all the files in `data/raw/census_sal/`.
7. Run `make build`. The pipeline logs each file's checksum and retrieval date in `sources.md`.

The exact category labels get mapped in `config/pipeline.toml` → `[census]` once the first export exists.
