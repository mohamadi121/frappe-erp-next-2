import pytest

from asoud_erp.services.self_service import (
    coordinates,
    date_span,
    normalize_costings,
    normalize_expenses,
    normalize_itinerary,
)


def test_date_span_and_coordinates() -> None:
    assert date_span("2026-09-24", "2026-09-26") == ("2026-09-24", "2026-09-26")
    assert coordinates(None, "") is None
    assert coordinates("35.7", 51.4) == (35.7, 51.4)
    for args in (("2026-09-26", "2026-09-24"), ("1405/07/02", "2026-09-26")):
        with pytest.raises(ValueError):
            date_span(*args)
    for args in ((91, 0), (0, 181), ("x", 1), (35.7, None)):
        with pytest.raises(ValueError):
            coordinates(*args)


def test_itinerary_rows() -> None:
    rows = normalize_itinerary('[{"travel_from": "تهران", "travel_to": "اصفهان",'
                               ' "departure_date": "2026-10-01", "arrival_date": "2026-10-03",'
                               ' "mode_of_travel": "Rail"}]')
    assert rows == [{"travel_from": "تهران", "travel_to": "اصفهان", "departure_date": "2026-10-01",
                     "arrival_date": "2026-10-03", "mode_of_travel": "Rail"}]


@pytest.mark.parametrize("itinerary", [
    [], [{"travel_to": "B", "departure_date": "2026-10-01"}],
    [{"travel_from": "A", "travel_to": "B", "departure_date": "2026-10-03", "arrival_date": "2026-10-01"}],
    [{"travel_from": "A", "travel_to": "B", "departure_date": "2026-10-01", "mode_of_travel": "Ship"}],
])
def test_invalid_itinerary(itinerary) -> None:
    with pytest.raises(ValueError):
        normalize_itinerary(itinerary)


def test_costings_and_expenses() -> None:
    assert normalize_costings(None) == []
    assert normalize_costings([{"expense_type": "Travel", "total_amount": "500"}])[0]["total_amount"] == 500.0
    rows = normalize_expenses([{"expense_type": "Food", "expense_date": "2026-09-20", "amount": 120,
                                "description": "ناهار"}])
    assert rows == [{"expense_type": "Food", "expense_date": "2026-09-20", "amount": 120.0,
                     "description": "ناهار"}]
    for bad in ([], [{"expense_type": "Food", "expense_date": "2026-09-20", "amount": 0}],
                [{"expense_date": "2026-09-20", "amount": 1}]):
        with pytest.raises(ValueError):
            normalize_expenses(bad)
