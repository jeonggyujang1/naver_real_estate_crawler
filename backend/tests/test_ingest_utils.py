import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.parsers import parse_confirmed_date, price_to_manwon


def test_price_to_manwon_handles_eok_unit() -> None:
    assert price_to_manwon("10억") == 100000
    assert price_to_manwon("10억 5,000") == 105000
    assert price_to_manwon("8500") == 8500
    assert price_to_manwon("invalid") is None


def test_parse_confirmed_date_multiple_formats() -> None:
    assert parse_confirmed_date("25.02.01.").isoformat() == "2025-02-01"
    assert parse_confirmed_date("2025.02.01.").isoformat() == "2025-02-01"
    assert parse_confirmed_date("2025-02-01").isoformat() == "2025-02-01"
    assert parse_confirmed_date("bad-format") is None
