from datetime import datetime

from app.core.material_service import _material_datetime_text


def test_material_datetime_text_keeps_naive_database_time_local():
    value = datetime(2026, 8, 21, 23, 2, 42, 808687)

    assert _material_datetime_text(value) == "2026-08-21T23:02:42"


def test_material_datetime_text_preserves_empty_values():
    assert _material_datetime_text(None) == ""
