from unittest.mock import Mock, patch

import pytest

from app import db
from app.geocoding.base import GeocodeResult
from app.geocoding.factory import get_geocoder
from app.geocoding.nominatim import NominatimGeocoder
from app.geocoding.service import geocode_pending


def test_geocode_result_holds_provider_fields():
    result = GeocodeResult(
        display_name="Chicago, IL, USA", city="Chicago", region="Illinois",
        country="USA", lat=41.8781, lng=-87.6298,
    )
    assert result.display_name == "Chicago, IL, USA"
    assert result.lat == 41.8781
    assert result.lng == -87.6298


def test_nominatim_geocode_parses_a_successful_response():
    fake_response = Mock()
    fake_response.json.return_value = [{
        "lat": "41.8781136", "lon": "-87.6297982",
        "display_name": "Chicago, Cook County, Illinois, United States",
        "address": {"city": "Chicago", "state": "Illinois", "country": "United States"},
    }]
    fake_response.raise_for_status = Mock()

    with patch("app.geocoding.nominatim.requests.get", return_value=fake_response) as mock_get:
        result = NominatimGeocoder().geocode("Chicago, IL")

    assert result.display_name == "Chicago, Cook County, Illinois, United States"
    assert result.city == "Chicago"
    assert result.region == "Illinois"
    assert result.country == "United States"
    assert result.lat == 41.8781136
    assert result.lng == -87.6297982
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["q"] == "Chicago, IL"
    assert "CareerSpyder" in kwargs["headers"]["User-Agent"]


def test_nominatim_geocode_uses_structured_params_for_bare_zip():
    fake_response = Mock()
    fake_response.json.return_value = [{
        "lat": "41.8827", "lon": "-88.0075",
        "display_name": "60148, DuPage County, Illinois, United States",
        "address": {"town": "Lombard", "state": "Illinois", "country": "United States"},
    }]
    fake_response.raise_for_status = Mock()

    with patch("app.geocoding.nominatim.requests.get", return_value=fake_response) as mock_get:
        result = NominatimGeocoder().geocode("60148")

    assert result is not None
    assert result.lat == 41.8827
    _, kwargs = mock_get.call_args
    assert "q" not in kwargs["params"]
    assert kwargs["params"]["postalcode"] == "60148"
    assert kwargs["params"]["countrycodes"] == "us"


def test_nominatim_geocode_uses_structured_params_for_zip_plus_4():
    fake_response = Mock()
    fake_response.json.return_value = [{
        "lat": "41.8827", "lon": "-88.0075",
        "display_name": "60148, DuPage County, Illinois, United States",
        "address": {"town": "Lombard", "state": "Illinois", "country": "United States"},
    }]
    fake_response.raise_for_status = Mock()

    with patch("app.geocoding.nominatim.requests.get", return_value=fake_response) as mock_get:
        result = NominatimGeocoder().geocode("60148-3401")

    assert result is not None
    _, kwargs = mock_get.call_args
    assert "q" not in kwargs["params"]
    assert kwargs["params"]["postalcode"] == "60148"
    assert kwargs["params"]["countrycodes"] == "us"


def test_nominatim_geocode_uses_free_text_for_city_state_query():
    fake_response = Mock()
    fake_response.json.return_value = [{
        "lat": "41.8781136", "lon": "-87.6297982",
        "display_name": "Chicago, Cook County, Illinois, United States",
        "address": {"city": "Chicago", "state": "Illinois", "country": "United States"},
    }]
    fake_response.raise_for_status = Mock()

    with patch("app.geocoding.nominatim.requests.get", return_value=fake_response) as mock_get:
        NominatimGeocoder().geocode("Chicago, IL")

    _, kwargs = mock_get.call_args
    assert "q" in kwargs["params"]
    assert "postalcode" not in kwargs["params"]


def test_nominatim_geocode_uses_free_text_for_zip_with_country_suffix():
    """'60148, USA' is not a bare ZIP — passes through free-text as entered."""
    fake_response = Mock()
    fake_response.json.return_value = [{
        "lat": "41.8827", "lon": "-88.0075",
        "display_name": "60148, DuPage County, Illinois, United States",
        "address": {"town": "Lombard", "state": "Illinois", "country": "United States"},
    }]
    fake_response.raise_for_status = Mock()

    with patch("app.geocoding.nominatim.requests.get", return_value=fake_response) as mock_get:
        NominatimGeocoder().geocode("60148, USA")

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["q"] == "60148, USA"
    assert "postalcode" not in kwargs["params"]


def test_nominatim_geocode_falls_back_to_town_when_no_city_field():
    fake_response = Mock()
    fake_response.json.return_value = [{
        "lat": "44.9", "lon": "-93.1", "display_name": "Small Town, USA",
        "address": {"town": "Small Town", "state": "MN", "country": "USA"},
    }]
    fake_response.raise_for_status = Mock()

    with patch("app.geocoding.nominatim.requests.get", return_value=fake_response):
        result = NominatimGeocoder().geocode("Small Town, MN")

    assert result.city == "Small Town"


def test_nominatim_geocode_returns_none_for_no_results():
    fake_response = Mock()
    fake_response.json.return_value = []
    fake_response.raise_for_status = Mock()

    with patch("app.geocoding.nominatim.requests.get", return_value=fake_response):
        result = NominatimGeocoder().geocode("Nowhere, XX")

    assert result is None


def test_nominatim_geocode_returns_none_on_request_exception():
    import requests

    with patch("app.geocoding.nominatim.requests.get", side_effect=requests.RequestException("boom")):
        result = NominatimGeocoder().geocode("Chicago, IL")

    assert result is None


def test_get_geocoder_defaults_to_nominatim(monkeypatch):
    monkeypatch.delenv("GEOCODER_PROVIDER", raising=False)
    assert isinstance(get_geocoder(), NominatimGeocoder)


def test_get_geocoder_reads_provider_from_env(monkeypatch):
    monkeypatch.setenv("GEOCODER_PROVIDER", "nominatim")
    assert isinstance(get_geocoder(), NominatimGeocoder)


def test_get_geocoder_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setenv("GEOCODER_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError, match="not-a-real-provider"):
        get_geocoder()


class _FakeGeocoder:
    name = "fake"
    min_interval_seconds = 0.0

    def __init__(self, results=None, raises_for=()):
        self.results = results or {}
        self.raises_for = set(raises_for)
        self.calls = []

    def geocode(self, location):
        self.calls.append(location)
        if location in self.raises_for:
            raise RuntimeError("provider outage")
        return self.results.get(location)


def test_geocode_pending_resolves_a_pending_location(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    conn.execute("INSERT INTO geocoded_locations (location, status) VALUES ('Chicago, IL', 'pending')")
    conn.commit()
    geocoder = _FakeGeocoder(results={
        "Chicago, IL": GeocodeResult(display_name="Chicago, IL, USA", city="Chicago",
                                      region="Illinois", country="USA", lat=41.8, lng=-87.6),
    })

    geocode_pending(conn, geocoder)

    row = conn.execute(
        "SELECT status, display_name, city, region, country, lat, lng, provider "
        "FROM geocoded_locations WHERE location = 'Chicago, IL'"
    ).fetchone()
    assert row == ("resolved", "Chicago, IL, USA", "Chicago", "Illinois", "USA", 41.8, -87.6, "fake")


def test_geocode_pending_marks_a_location_failed_when_geocoder_returns_none(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    conn.execute("INSERT INTO geocoded_locations (location, status) VALUES ('Remote', 'pending')")
    conn.commit()
    geocoder = _FakeGeocoder(results={"Remote": None})

    geocode_pending(conn, geocoder)

    row = conn.execute("SELECT status FROM geocoded_locations WHERE location = 'Remote'").fetchone()
    assert row == ("failed",)


def test_geocode_pending_never_requeries_already_resolved_or_failed_rows(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    conn.execute(
        "INSERT INTO geocoded_locations (location, status) VALUES "
        "('Chicago, IL', 'resolved'), ('Remote', 'failed'), ('New York, NY', 'pending')"
    )
    conn.commit()
    geocoder = _FakeGeocoder(results={"New York, NY": GeocodeResult(
        display_name="New York, NY, USA", city="New York", region="New York",
        country="USA", lat=40.7, lng=-74.0,
    )})

    geocode_pending(conn, geocoder)

    assert geocoder.calls == ["New York, NY"]


def test_geocode_pending_catches_a_per_location_exception_and_marks_it_failed(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    conn.execute(
        "INSERT INTO geocoded_locations (location, status) VALUES "
        "('Boom Town', 'pending'), ('Chicago, IL', 'pending')"
    )
    conn.commit()
    geocoder = _FakeGeocoder(
        results={"Chicago, IL": GeocodeResult(display_name="Chicago, IL, USA", city="Chicago",
                                               region="Illinois", country="USA", lat=41.8, lng=-87.6)},
        raises_for=["Boom Town"],
    )

    geocode_pending(conn, geocoder)

    boom_row = conn.execute("SELECT status FROM geocoded_locations WHERE location = 'Boom Town'").fetchone()
    chicago_row = conn.execute("SELECT status FROM geocoded_locations WHERE location = 'Chicago, IL'").fetchone()
    assert boom_row == ("failed",)
    assert chicago_row == ("resolved",)
