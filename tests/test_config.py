"""Tests for config.py — configuration loading and validation."""

import json

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
