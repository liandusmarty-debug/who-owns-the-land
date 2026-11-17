from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wotl.clean import OwnerTypeClassifier
from wotl.cli import build_pipeline
from wotl.config import IndicatorSpec, PipelineConfig
from wotl.index import DeprivationIndex, Indicator, MinMax, ZScore
from wotl.pipeline import Context
from wotl.privacy import PrivacyError, PrivacyGuard

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg() -> PipelineConfig:
    return PipelineConfig.load(ROOT / "config" / "pipeline.toml")


def test_owner_classifier(cfg):
    c = OwnerTypeClassifier(cfg.owner_rules, cfg.owner_default, cfg.owner_categories)
    assert c.classify_one("CITY OF CAPE TOWN") == "City"
    assert c.classify_one("Western Cape Provincial Government") == "Province"
    assert c.classify_one("REPUBLIC OF SOUTH AFRICA") == "National"
    assert c.classify_one("Smith Family Trust") == "Other"
    assert c.classify_one("J SOMEONE") == "Private"


def test_privacy_guard_blocks_names():
    g = PrivacyGuard(frozenset({"owner_name"}), 30)
    df = pd.DataFrame({"owner_name": ["x"], "owner_type": ["Private"]})
    with pytest.raises(PrivacyError):
        g.assert_clean(df, "t")
    assert list(g.strip(df).columns) == ["owner_type"]


def test_index_ranks_worse_area_first():
    df = pd.DataFrame({"bad": [90, 10, 50], "hh": [100, 100, 100]})
    spec = IndicatorSpec("bad", "Bad", "bad", "hh")
    for norm in (ZScore(), MinMax()):
        out = DeprivationIndex([Indicator(spec)], norm, quintiles=3).compute(df, pd.Series([True] * 3))
        assert list(out["deprivation_rank"]) == [1, 3, 2]
        assert list(out["deprivation_quintile"]) == [3, 1, 2]


def test_ineligible_areas_not_ranked():
    df = pd.DataFrame({"bad": [90, 10, 50], "hh": [100, 100, 100]})
    spec = IndicatorSpec("bad", "Bad", "bad", "hh")
    out = DeprivationIndex([Indicator(spec)], ZScore(), 2).compute(df, pd.Series([True, True, False]))
    assert np.isnan(out.loc[2, "deprivation_index"])


def test_sample_build_end_to_end(cfg, tmp_path):
    # run against a temp root so tests never touch real data/outputs
    import shutil
    from dataclasses import replace

    from wotl.config import Paths

    shutil.copytree(ROOT / "web", tmp_path / "web")
    c = replace(cfg, paths=Paths(tmp_path))
    ctx = build_pipeline(sample=True).run(Context(c, sample_mode=True))
    out = ctx.outputs_dir
    for f in ("neighbourhood_profiles.csv", "summary.md", "map.html", "data/areas.js", "profile_masiphumelele.md"):
        assert (out / f).exists(), f
    prof = pd.read_csv(out / "neighbourhood_profiles.csv")
    assert "owner_name" not in prof.columns
    assert prof.loc[prof["suppressed"], "deprivation_rank"].isna().all()
    own = prof.filter(like="own_").sum(axis=1)
    assert own.between(99, 101).all()  # ownership shares (incl. unmapped) sum to ~100%
