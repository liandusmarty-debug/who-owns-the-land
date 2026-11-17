from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from wotl.clean import OwnerTypeResolver
from wotl.config import PipelineConfig
from wotl.ownership import OwnershipOverlay

ROOT = Path(__file__).resolve().parents[1]
CRS = "EPSG:32734"


@pytest.fixture(scope="module")
def cfg():
    return PipelineConfig.load(ROOT / "config" / "pipeline.toml")


def parcels():
    geoms = [box(i * 100, 0, i * 100 + 90, 90) for i in range(4)]
    return gpd.GeoDataFrame({"sg26_code": ["A", "B", "C", "D"]}, geometry=geoms, crs=CRS).to_crs(4326)


def test_precedence_list_then_public_layer_then_unknown(cfg):
    owner_list = pd.DataFrame(
        {"sg26_code": ["A", "B"], "owner_type": ["Province", ""], "owner_name": ["", "SOMEONE PRIVATE"]}
    )
    public = {
        "sg_public_places": gpd.GeoDataFrame(geometry=[box(195, -5, 295, 95), box(-5, -5, 95, 95)], crs=CRS).to_crs(
            4326
        )
    }
    out = OwnerTypeResolver(cfg).resolve(parcels(), owner_list, public).set_index("sg26_code")
    assert out.loc["A", "owner_type"] == "Province"  # list beats the public layer covering A
    assert out.loc["B", "owner_type"] == "Private"  # raw name classified
    assert out.loc["C", "owner_type"] == "City"  # public place
    assert out.loc["D", "owner_type"] == "Unknown"  # never assumed private
    assert "owner_name" not in out.columns


def test_works_with_no_owner_list_yet(cfg):
    # the real situation before any data request is answered
    public = {"sg_state_land": gpd.GeoDataFrame(geometry=[box(-5, -5, 95, 95)], crs=CRS).to_crs(4326)}
    out = OwnerTypeResolver(cfg).resolve(parcels(), None, public).set_index("sg26_code")
    assert out.loc["A", "owner_type"] == "National"
    assert (out.loc[["B", "C", "D"], "owner_type"] == "Unknown").all()


def test_invalid_owner_type_is_rejected(cfg):
    bad = pd.DataFrame({"sg26_code": ["A"], "owner_type": ["Government-ish"]})
    with pytest.raises(ValueError, match="unknown owner_type"):
        OwnerTypeResolver(cfg).resolve(parcels(), bad, {})


def test_large_parcel_split_exactly_across_zones():
    # one 2 km x 100 m parcel straddling two zones: must be split, not given to one zone
    big = gpd.GeoDataFrame({"owner_type": ["National"]}, geometry=[box(0, 0, 2000, 100)], crs=CRS)
    zones = gpd.GeoDataFrame({"z": ["west", "east"]}, geometry=[box(0, 0, 1000, 100), box(1000, 0, 2000, 100)], crs=CRS)
    shares = OwnershipOverlay(big, ("National", "Unknown"), CRS).shares(zones, "z")
    assert shares.loc["west", "own_national_pct"] == pytest.approx(100, abs=0.5)
    assert shares.loc["east", "own_national_pct"] == pytest.approx(100, abs=0.5)
