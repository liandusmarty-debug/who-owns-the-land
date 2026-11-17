# ruff: noqa: E501  (fixture CSVs reproduce real SuperWEB2 export lines verbatim)
import pytest

from wotl.census import Census2011Builder, CountRule, TableSpec, normalise, read_superweb_csv

SUPERWEB = """"Census 2011"
"Type of main dwelling by Small Area"
"Counting: Households"

"Small Area","House or brick/concrete block structure","Informal dwelling (shack; in backyard)","Informal dwelling (shack; not in backyard)","Unspecified","Total",
"1990001","80","10","5","5","100",
"SAL 1990002","1 200","0","300","0","1500",

"Data Source: Statistics South Africa, Census 2011"
"""

EMPLOYMENT = """"Small Area","Employed","Unemployed","Discouraged work-seeker","Age less than 15 years","Not applicable","Total"
"1990001","30","10","5","20","1","66"
"1990002","400","100","50","300","0","850"
"""


def test_normalise():
    assert normalise("Piped (tap) water inside yard") == "pipedtapwaterinsideyard"
    assert normalise("R 19 601 - R 38 200") == "r19601r38200"


def test_read_superweb_handles_titles_footer_trailing_comma_and_spaces(tmp_path):
    f = tmp_path / "dwelling_type.csv"
    f.write_text(SUPERWEB)
    df = read_superweb_csv(f)
    assert list(df.index) == ["1990001", "1990002"]
    assert df.loc["1990002", "House or brick/concrete block structure"] == 1200
    assert "" not in df.columns and "Total" in df.columns


def test_builder_totals_matches_and_not_rules(tmp_path):
    (tmp_path / "dwelling_type.csv").write_text(SUPERWEB)
    (tmp_path / "employment_status.csv").write_text(EMPLOYMENT)
    tables = (
        TableSpec(
            "dwelling_type",
            "dwelling_type",
            total="households",
            counts=(
                CountRule("hh_informal", match=("informaldwelling",)),
                CountRule("hh_formal", not_match=("informaldwelling",)),
            ),
        ),
        TableSpec(
            "employment_status",
            "employment_status",
            total_all="population",
            counts=(
                CountRule("labour_force", match=("^employed$", "^unemployed$")),
                CountRule("unemployed", match=("^unemployed$",)),
            ),
        ),
    )
    out = Census2011Builder(tables, ("^total$", "unspecified", "notapplicable")).build(tmp_path).set_index("sal_code")
    assert out.loc["1990001", "households"] == 95  # unspecified + total excluded
    assert out.loc["1990001", "hh_informal"] == 15
    assert out.loc["1990001", "hh_formal"] == 80
    assert out.loc["1990001", "population"] == 66  # every category incl. not applicable, minus Total
    assert out.loc["1990002", "labour_force"] == 500  # "unemployed" must not match "^employed$"
    assert out.loc["1990002", "unemployed"] == 100


def test_rule_matching_nothing_fails_loudly(tmp_path):
    (tmp_path / "dwelling_type.csv").write_text(SUPERWEB)
    spec = TableSpec("dwelling_type", "dwelling_type", counts=(CountRule("x", match=("caravan",)),))
    with pytest.raises(ValueError, match="matched no categories"):
        Census2011Builder((spec,), ()).build(tmp_path)


def test_missing_export_explains_where_to_get_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="SuperWEB2"):
        Census2011Builder((TableSpec("piped_water", "piped_water"),), ()).build(tmp_path)
