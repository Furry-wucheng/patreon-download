"""Tests for downloader.py — hash registry and dedup logic."""

import json
from pathlib import Path

import pytest

from patreon_download.downloader import HashRegistry, _compute_hash, _collect_tasks
from patreon_download.models import MediaItem


class TestHashRegistry:
    """Test the hash registry for content-based dedup."""

    def test_create_empty_registry(self, tmp_path):
        reg = HashRegistry(tmp_path)
        assert reg._data == {}
        assert reg.has_hash("abc123") is False

    def test_register_and_lookup(self, tmp_path):
        reg = HashRegistry(tmp_path)
        reg.register("abc123", "file.jpg")
        assert reg.has_hash("abc123") is True
        assert reg.get_path("abc123") == "file.jpg"

    def test_save_and_reload(self, tmp_path):
        reg = HashRegistry(tmp_path)
        reg.register("hash1", "a.jpg")
        reg.register("hash2", "b.png")
        reg.save()

        # Reload from disk
        reg2 = HashRegistry(tmp_path)
        assert reg2.has_hash("hash1") is True
        assert reg2.get_path("hash2") == "b.png"

    def test_corrupted_registry_file(self, tmp_path):
        (tmp_path / ".hashes.json").write_text("NOT JSON", encoding="utf-8")
        reg = HashRegistry(tmp_path)
        assert reg._data == {}

    def test_thread_safety(self, tmp_path):
        """Register from multiple threads doesn't crash."""
        import threading
        reg = HashRegistry(tmp_path)
        errors = []

        def register_many(start):
            try:
                for i in range(50):
                    reg.register(f"hash_{start}_{i}", f"file_{start}_{i}.jpg")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_many, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(reg._data) == 200


class TestComputeHash:
    """Test SHA256 hash computation."""

    def test_hash_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world")
        h = _compute_hash(f)
        assert len(h) == 64  # SHA256 hex
        assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_same_content_same_hash(self, tmp_path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"identical content")
        b.write_bytes(b"identical content")
        assert _compute_hash(a) == _compute_hash(b)

    def test_different_content_different_hash(self, tmp_path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"content A")
        b.write_bytes(b"content B")
        assert _compute_hash(a) != _compute_hash(b)


class TestCollectTasks:
    """Test task collection with skip_existing."""

    def test_collect_all_when_none_exist(self, tmp_path):
        items = [
            MediaItem(id="1", url="https://example.com/a.jpg", filename="a.jpg"),
            MediaItem(id="2", url="https://example.com/b.jpg", filename="b.jpg"),
        ]
        tasks, skipped = _collect_tasks(items, tmp_path, "cookie")
        assert len(tasks) == 2
        assert skipped == 0

    def test_skip_existing_files(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"data")
        items = [
            MediaItem(id="1", url="https://example.com/a.jpg", filename="a.jpg"),
            MediaItem(id="2", url="https://example.com/b.jpg", filename="b.jpg"),
        ]
        tasks, skipped = _collect_tasks(items, tmp_path, "cookie", skip_existing=True)
        assert len(tasks) == 1
        assert skipped == 1
        assert tasks[0][1].name == "b.jpg"

    def test_no_skip_when_disabled(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"data")
        items = [
            MediaItem(id="1", url="https://example.com/a.jpg", filename="a.jpg"),
            MediaItem(id="2", url="https://example.com/b.jpg", filename="b.jpg"),
        ]
        tasks, skipped = _collect_tasks(items, tmp_path, "cookie", skip_existing=False)
        assert len(tasks) == 2
        assert skipped == 0

    def test_skip_none_url_items(self, tmp_path):
        items = [
            MediaItem(id="1", url=None, filename="a.jpg"),
            MediaItem(id="2", url="https://example.com/b.jpg", filename="b.jpg"),
        ]
        tasks, skipped = _collect_tasks(items, tmp_path, "cookie")
        assert len(tasks) == 1
