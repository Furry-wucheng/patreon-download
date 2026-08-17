"""Tests for config.py — configuration loading and validation."""

import json
from pathlib import Path

import pytest

from patreon_download.config import Config


class TestConfigDefaults:
    """Test default config values."""

    def test_empty_config_has_defaults(self):
        config = Config()
        assert config.cookie == ""
        assert config.output_dir == "./downloads"
        assert config.request_delay == 2.0
        assert config.max_retries == 3
        assert config.post_dir_format == "{yyyy}-{mm}-{dd}_{title}"
        assert config.output_info_json is True
        assert config.enable_threading is False
        assert config.max_workers == 4
        assert config.skip_existing is True
        assert config.date_from == ""
        assert config.date_to == ""
        assert config.source_path is None

    def test_validation_fails_without_cookie(self):
        config = Config()
        errors = config.validate()
        assert len(errors) == 1
        assert "Cookie" in errors[0]


class TestConfigLoad:
    """Test loading config from file."""

    def test_load_from_explicit_path(self, tmp_path):
        data = {"cookie": "my_cookie", "output_dir": "/tmp/out", "request_delay": 1.5}
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        config = Config.load(str(path))
        assert config.cookie == "my_cookie"
        assert config.output_dir == "/tmp/out"
        assert config.request_delay == 1.5
        assert config.max_retries == 3  # default
        assert config.post_dir_format == "{yyyy}-{mm}-{dd}_{title}"  # default

    def test_load_custom_post_dir_format(self, tmp_path):
        data = {"cookie": "c", "post_dir_format": "{id}_{author}_{title}"}
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        config = Config.load(str(path))
        assert config.post_dir_format == "{id}_{author}_{title}"

    def test_load_output_info_json_false(self, tmp_path):
        data = {"cookie": "c", "output_info_json": False}
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        config = Config.load(str(path))
        assert config.output_info_json is False

    def test_load_threading_config(self, tmp_path):
        data = {"cookie": "c", "enable_threading": True, "max_workers": 8}
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        config = Config.load(str(path))
        assert config.enable_threading is True
        assert config.max_workers == 8

    def test_load_skip_existing_false(self, tmp_path):
        data = {"cookie": "c", "skip_existing": False}
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        config = Config.load(str(path))
        assert config.skip_existing is False

    def test_load_missing_file_returns_defaults(self, monkeypatch):
        # Prevent fallback to real config.json in project root
        monkeypatch.setattr("pathlib.Path.is_file", lambda self: False)
        config = Config.load("/nonexistent/path/config.json")
        assert config.cookie == ""
        assert config.output_dir == "./downloads"

    def test_validation_passes_with_cookie(self, tmp_path):
        data = {"cookie": "valid_cookie"}
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        config = Config.load(str(path))
        errors = config.validate()
        assert errors == []

    def test_load_date_filter_fields(self, tmp_path):
        data = {
            "cookie": "c",
            "date_from": "2024-01-01",
            "date_to": "2024-12-31",
        }
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        config = Config.load(str(path))
        assert config.date_from == "2024-01-01"
        assert config.date_to == "2024-12-31"

    def test_load_records_source_path(self, tmp_path):
        data = {"cookie": "c"}
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        config = Config.load(str(path))
        assert config.source_path == path

    def test_validate_rejects_bad_date(self):
        config = Config(cookie="c", date_from="not-a-date")
        errors = config.validate()
        assert any("date_from" in e for e in errors)

    def test_validate_rejects_reversed_range(self):
        config = Config(cookie="c", date_from="2025-12-31", date_to="2025-01-01")
        errors = config.validate()
        assert any("date_from" in e for e in errors)


class TestConfigSave:
    """Test writing config back to a JSON file."""

    def test_save_round_trip(self, tmp_path):
        path = tmp_path / "cfg.json"
        config = Config(
            cookie="secret_cookie",
            output_dir="G:/out",
            request_delay=3.5,
            max_retries=5,
            post_dir_format="{id}_{title}",
            output_info_json=False,
            enable_threading=True,
            max_workers=8,
            skip_existing=False,
            date_from="2024-03-01",
            date_to="2024-05-31",
        )
        saved = config.save(path)

        assert saved == path
        assert path.is_file()
        assert config.source_path == path

        reloaded = Config.load(str(path))
        assert reloaded.cookie == "secret_cookie"
        assert reloaded.output_dir == "G:/out"
        assert reloaded.request_delay == 3.5
        assert reloaded.max_retries == 5
        assert reloaded.post_dir_format == "{id}_{title}"
        assert reloaded.output_info_json is False
        assert reloaded.enable_threading is True
        assert reloaded.max_workers == 8
        assert reloaded.skip_existing is False
        assert reloaded.date_from == "2024-03-01"
        assert reloaded.date_to == "2024-05-31"

    def test_save_writes_back_to_source_path(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps({"cookie": "old"}), encoding="utf-8")

        config = Config.load(str(path))
        config.cookie = "new_cookie"
        config.save()

        reloaded = Config.load(str(path))
        assert reloaded.cookie == "new_cookie"

    def test_save_default_path_is_config_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = Config(cookie="c")
        saved = config.save()
        # 无 source_path 时默认写到当前目录的 config.json（相对路径）
        assert saved == Path("config.json")
        assert (tmp_path / "config.json").is_file()
        assert Config.load().cookie == "c"

    def test_to_dict_contains_all_fields(self):
        config = Config(cookie="c", date_from="2025-01-01")
        data = config.to_dict()
        assert data["cookie"] == "c"
        assert data["date_from"] == "2025-01-01"
        assert data["date_to"] == ""
        assert "source_path" not in data
