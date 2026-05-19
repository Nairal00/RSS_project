from __future__ import annotations

import json
from pathlib import Path

import pytest

import cache as cache_module
from cache import get_cached, load_cache, save_cache, update_cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_cache_path(tmp_path, monkeypatch):
    """Redirect all cache I/O to a temp directory for every test."""
    monkeypatch.setattr(cache_module, "CACHE_PATH", tmp_path / "cache.json")


# ---------------------------------------------------------------------------
# load_cache
# ---------------------------------------------------------------------------

class TestLoadCache:
    def test_missing_file_returns_empty_dict(self):
        assert load_cache() == {}

    def test_valid_json_returns_correct_dict(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(
            json.dumps({"https://example.com": {"is_ai_related": True}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(cache_module, "CACHE_PATH", cache_file)
        result = load_cache()
        assert result == {"https://example.com": {"is_ai_related": True}}

    def test_corrupted_json_returns_empty_dict(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("not valid json {{{", encoding="utf-8")
        monkeypatch.setattr(cache_module, "CACHE_PATH", cache_file)
        result = load_cache()
        assert result == {}

    def test_corrupted_json_prints_warning(self, tmp_path, monkeypatch, capsys):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("{bad json}", encoding="utf-8")
        monkeypatch.setattr(cache_module, "CACHE_PATH", cache_file)
        load_cache()
        assert "[WARNING]" in capsys.readouterr().out

    def test_empty_json_object_returns_empty_dict(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(cache_module, "CACHE_PATH", cache_file)
        assert load_cache() == {}


# ---------------------------------------------------------------------------
# save_cache + load_cache (round-trip)
# ---------------------------------------------------------------------------

class TestSaveCache:
    def test_creates_file(self):
        save_cache({"key": "value"})
        assert cache_module.CACHE_PATH.exists()

    def test_round_trip_preserves_data(self):
        data = {
            "https://example.com": {"is_ai_related": True, "ai_summary": "Summary text"},
            "https://other.com": {"is_ai_related": False, "ai_summary": None},
        }
        save_cache(data)
        assert load_cache() == data

    def test_overwrites_previous_content(self):
        save_cache({"old": "data"})
        save_cache({"new": "data"})
        result = load_cache()
        assert result == {"new": "data"}
        assert "old" not in result

    def test_unicode_content_preserved(self):
        data = {"https://example.com": {"ai_summary": "AI的未来：深度学习"}}
        save_cache(data)
        assert load_cache() == data


# ---------------------------------------------------------------------------
# get_cached
# ---------------------------------------------------------------------------

class TestGetCached:
    @pytest.fixture
    def sample_cache(self) -> dict:
        return {
            "https://example.com/article": {
                "is_ai_related": True,
                "ai_summary": "Test summary",
            }
        }

    def test_known_url_returns_data(self, sample_cache):
        result = get_cached(sample_cache, "https://example.com/article")
        assert result == {"is_ai_related": True, "ai_summary": "Test summary"}

    def test_unknown_url_returns_none(self, sample_cache):
        assert get_cached(sample_cache, "https://unknown.com") is None

    def test_empty_cache_returns_none(self):
        assert get_cached({}, "https://example.com") is None

    def test_does_not_mutate_cache(self, sample_cache):
        original_len = len(sample_cache)
        get_cached(sample_cache, "https://new.com")
        assert len(sample_cache) == original_len


# ---------------------------------------------------------------------------
# update_cache
# ---------------------------------------------------------------------------

class TestUpdateCache:
    def test_adds_new_entry(self):
        cache: dict = {}
        update_cache(cache, "https://example.com", {"is_ai_related": True})
        assert cache["https://example.com"] == {"is_ai_related": True}

    def test_overwrites_existing_entry(self):
        cache = {"https://example.com": {"is_ai_related": False}}
        update_cache(cache, "https://example.com", {"is_ai_related": True})
        assert cache["https://example.com"]["is_ai_related"] is True

    def test_does_not_affect_other_entries(self):
        cache = {"https://other.com": {"is_ai_related": True}}
        update_cache(cache, "https://new.com", {"is_ai_related": False})
        assert cache["https://other.com"]["is_ai_related"] is True

    @pytest.mark.parametrize("url,data", [
        ("https://a.com", {"is_ai_related": True, "ai_summary": "x"}),
        ("https://b.com", {"is_ai_related": False, "ai_summary": None}),
        ("https://c.com", {}),
    ])
    def test_various_data_shapes(self, url: str, data: dict):
        cache: dict = {}
        update_cache(cache, url, data)
        assert cache[url] == data
