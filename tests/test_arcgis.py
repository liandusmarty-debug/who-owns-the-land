import json

from wotl.config import SourceSpec
from wotl.ingest import ArcGISLayerFetcher


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self.payload


class FakeSession:
    """Serves a 5-feature layer with maxRecordCount=2, like a real ArcGIS server."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.features = [
            {"type": "Feature", "properties": {"id": i}, "geometry": {"type": "Point", "coordinates": [18.4, -34.0]}}
            for i in range(5)
        ]

    def get(self, url: str, params: dict, timeout: int) -> FakeResponse:
        self.calls.append({"url": url, **params})
        if not url.endswith("/query"):
            return FakeResponse({"name": "Fake layer", "maxRecordCount": 2, "copyrightText": "Test"})
        off, n = params["resultOffset"], params["resultRecordCount"]
        page = self.features[off : off + n]
        return FakeResponse({"type": "FeatureCollection", "features": page, "exceededTransferLimit": off + n < 5})


def test_fetcher_pages_through_all_features(tmp_path):
    session = FakeSession()
    spec = SourceSpec("x", "X", "P", "L", url="https://example.org/MapServer/1", kind="arcgis", out_fields="id")
    n = ArcGISLayerFetcher(session).fetch(spec, tmp_path / "x.geojson")
    assert n == 5
    data = json.loads((tmp_path / "x.geojson").read_text())
    assert [f["properties"]["id"] for f in data["features"]] == [0, 1, 2, 3, 4]
    offsets = [c["resultOffset"] for c in session.calls if "resultOffset" in c]
    assert offsets == [0, 2, 4]
    assert json.loads((tmp_path / "query.json").read_text())["copyright"] == "Test"


def test_bbox_becomes_envelope_filter():
    spec = SourceSpec("x", "X", "P", "L", url="u", kind="arcgis", bbox=(18.3, -34.4, 19.0, -33.5))
    params = ArcGISLayerFetcher(FakeSession()).query_params(spec)
    assert params["geometry"] == "18.3,-34.4,19.0,-33.5"
    assert params["geometryType"] == "esriGeometryEnvelope"
    assert params["outSR"] == 4326
