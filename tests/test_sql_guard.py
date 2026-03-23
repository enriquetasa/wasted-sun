import pytest

from wasted_sun.sql_guard import (
    validate_as_of_select,
    validate_pg_identifier,
    validate_pg_qualified_table,
    validate_plausible_domain,
    validate_plausible_script_url,
    validate_qh_slots,
)


def test_rejects_bad_identifiers():
    with pytest.raises(ValueError):
        validate_pg_identifier("foo-bar")
    with pytest.raises(ValueError):
        validate_pg_identifier("123x")
    with pytest.raises(ValueError):
        validate_pg_qualified_table("a.b.c")


def test_accepts_qualified_table():
    assert validate_pg_qualified_table("public.my_table") == "public.my_table"


def test_as_of_select_basic():
    q = "SELECT max(updated_at) FROM pipeline_meta"
    assert validate_as_of_select(q) == q


def test_as_of_select_rejects_injection():
    with pytest.raises(ValueError):
        validate_as_of_select("SELECT 1; DROP TABLE t")
    with pytest.raises(ValueError):
        validate_as_of_select("DELETE FROM t")
    with pytest.raises(ValueError):
        validate_as_of_select("-- comment\nSELECT 1")


def test_qh_slots_bounds():
    assert validate_qh_slots(96) == 96
    with pytest.raises(ValueError):
        validate_qh_slots(0)
    with pytest.raises(ValueError):
        validate_qh_slots(500)


def test_plausible_domain():
    assert validate_plausible_domain("") == ""
    assert validate_plausible_domain("stats.example.com") == "stats.example.com"
    with pytest.raises(ValueError):
        validate_plausible_domain("evil<script>")


def test_plausible_script_url():
    assert validate_plausible_script_url("") == ""
    u = "https://plausible.io/js/script.js"
    assert validate_plausible_script_url(u) == u
    with pytest.raises(ValueError):
        validate_plausible_script_url("javascript:alert(1)")
