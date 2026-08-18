from app.geocoding.base import GeocodeResult


def test_geocode_result_holds_provider_fields():
    result = GeocodeResult(
        display_name="Chicago, IL, USA", city="Chicago", region="Illinois",
        country="USA", lat=41.8781, lng=-87.6298,
    )
    assert result.display_name == "Chicago, IL, USA"
    assert result.lat == 41.8781
    assert result.lng == -87.6298
