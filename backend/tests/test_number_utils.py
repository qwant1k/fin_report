"""Tests for KZ number/date normalisation."""
from datetime import date, datetime

from services.parser.number_utils import parse_int, parse_kz_date, parse_kz_number, s


def test_parse_kz_number_with_space_and_comma():
    assert parse_kz_number("2 069 895 029") == 2069895029.0
    assert parse_kz_number("12 000 590,78") == 12000590.78
    assert parse_kz_number("16,5") == 16.5


def test_parse_kz_number_passes_through_floats():
    assert parse_kz_number(16.5) == 16.5
    assert parse_kz_number(0) == 0.0


def test_parse_kz_number_handles_placeholders():
    assert parse_kz_number(None) is None
    assert parse_kz_number("") is None
    assert parse_kz_number("-") is None
    assert parse_kz_number("  ") is None


def test_parse_kz_date_supports_known_formats():
    assert parse_kz_date("10.09.2025") == date(2025, 9, 10)
    assert parse_kz_date("2025-09-10") == date(2025, 9, 10)
    assert parse_kz_date(datetime(2025, 9, 10)) == date(2025, 9, 10)
    assert parse_kz_date(date(2025, 9, 10)) == date(2025, 9, 10)
    assert parse_kz_date(None) is None
    assert parse_kz_date("") is None


def test_parse_int():
    assert parse_int("1 234,5") == 1234  # rounded
    assert parse_int("0") == 0
    assert parse_int(None) is None


def test_strip_helper():
    assert s("  hello  ") == "hello"
    assert s("-") is None
    assert s(None) is None
