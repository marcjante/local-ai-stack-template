"""test_model_manager.py — listado, filtrado del catálogo disponible."""

from common.model_manager import list_available, CURATED_AVAILABLE, _format_size


def test_available_excludes_installed():
    installed = {CURATED_AVAILABLE[0]["name"]}
    available = list_available(installed)
    names = {m["name"] for m in available}
    assert CURATED_AVAILABLE[0]["name"] not in names
    assert len(available) == len(CURATED_AVAILABLE) - 1


def test_available_with_nothing_installed_returns_full_catalog():
    assert list_available(set()) == CURATED_AVAILABLE


def test_format_size():
    assert _format_size(4_700_000_000) == "4.4 GB"
    assert _format_size(None) == "—"
    assert _format_size(0) == "—"
