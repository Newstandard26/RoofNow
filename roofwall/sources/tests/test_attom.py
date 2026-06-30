"""ATTOM property enrichment — address split, parsing, fetch with fallback."""
import pytest

from roofwall.sources import attom


def test_split_address():
    assert attom.split_address("4150 N Rockton Ave, Rockford, IL 61101, USA") == \
        ("4150 N Rockton Ave", "Rockford, IL 61101")
    assert attom.split_address("1 Main St, Springfield, IL 62701") == \
        ("1 Main St", "Springfield, IL 62701")
    assert attom.split_address("nocommas") is None
    assert attom.split_address("") is None


_SAMPLE = {
    "status": {"code": 0, "msg": "SuccessWithResult", "total": 1},
    "property": [{
        "identifier": {"attomId": 123456},
        "summary": {"proptype": "SFR", "yearbuilt": 1998},
        "building": {
            "size": {"universalsize": 2400, "livingsize": 2200},
            "rooms": {"beds": 4, "bathstotal": 3},
            "summary": {"levels": 2},
            "construction": {"roofcover": "Asphalt", "roofframe": "Wood Truss"},
        },
        "lot": {"lotsize2": 9000},
        "owner": {"owner1": {"firstname": "Jane", "lastname": "Roof"}},
    }],
}


def test_parse_property():
    f = attom.parse_property(_SAMPLE)
    assert f["year_built"] == 1998
    assert f["building_sqft"] == 2400
    assert f["stories"] == "2"
    assert f["roof_cover"] == "Asphalt"
    assert f["beds"] == 4
    assert f["property_type"] == "SFR"
    assert f["owner"] == "Jane Roof"
    assert f["attom_id"] == "123456"


def test_parse_property_empty():
    assert attom.parse_property({"property": []}) is None
    assert attom.parse_property({}) is None
    # 200 but no useful roofing facts -> None
    assert attom.parse_property({"property": [{"summary": {"proptype": "SFR"}}]}) is None


def test_fetch_no_key(monkeypatch):
    monkeypatch.delenv("ATTOM_API_KEY", raising=False)
    assert attom.fetch_property_facts("1 Main St, Town, IL 60000") is None


def test_fetch_success_first_endpoint():
    calls = []
    def fake_get(url, headers, params):
        calls.append(url)
        assert headers["apikey"] == "k"
        assert params["address1"] == "1 Main St"
        return 200, _SAMPLE
    f = attom.fetch_property_facts("1 Main St, Town, IL 60000", api_key="k", http_get=fake_get)
    assert f["year_built"] == 1998
    assert f["endpoint"] == "property/expandedprofile"
    assert len(calls) == 1   # first endpoint succeeded


def test_fetch_falls_through_on_403():
    seen = []
    def fake_get(url, headers, params):
        seen.append(url.rsplit("/", 1)[-1])
        if url.endswith("expandedprofile"):
            return 403, {"status": {"code": 401}}
        return 200, _SAMPLE
    f = attom.fetch_property_facts("1 Main St, Town, IL 60000", api_key="k", http_get=fake_get)
    assert f["year_built"] == 1998
    assert seen[0] == "expandedprofile" and "detail" in seen


def test_fetch_all_fail_returns_none():
    def fake_get(url, headers, params):
        return 401, None
    assert attom.fetch_property_facts("1 Main St, Town, IL 60000", api_key="k", http_get=fake_get) is None
