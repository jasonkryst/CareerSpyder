from unittest.mock import Mock, patch

from app.geocoding.base import GeocodeResult
from app.geocoding.nominatim import NominatimGeocoder


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
