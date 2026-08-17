"""Tests for downloader.py — hash registry and dedup logic."""

import json
import threading
from pathlib import Path

import pytest

from patreon_download.downloader import (
    CancelledError,
    HashRegistry,
    _collect_tasks,
    _compute_hash,
    _download_batch_sequential,
    _download_file_progress,
)
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


class TestDownloadRetries:
    """Test retry behavior for media file downloads."""

    def test_progress_download_retries_then_succeeds(self, tmp_path, monkeypatch):
        class FakeResponse:
            headers = {"content-length": "4"}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                yield b"data"

        class FakeConsole:
            def print(self, *args, **kwargs):
                pass

        class FakeProgress:
            console = FakeConsole()

            def __init__(self):
                self.descriptions = []

            def reset(self, task_id, **kwargs):
                self.descriptions.append(kwargs.get("description", ""))

            def update(self, task_id, **kwargs):
                self.descriptions.append(kwargs.get("description", ""))

            def advance(self, task_id, amount):
                pass

        calls = 0

        def fake_get(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise OSError("temporary connection failure")
            return FakeResponse()

        delays = []
        monkeypatch.setattr("patreon_download.downloader.requests.get", fake_get)
        monkeypatch.setattr("patreon_download.downloader.time.sleep", delays.append)
        progress = FakeProgress()
        dest = tmp_path / "image.png"

        ok = _download_file_progress(
            "https://example.com/image.png",
            dest,
            "cookie",
            progress,
            task_id=1,
            max_retries=3,
        )

        assert ok is True
        assert calls == 3
        assert delays == [1, 2]
        assert dest.read_bytes() == b"data"
        assert any("RETRY 2/3" in text for text in progress.descriptions)
        assert any("RETRY 3/3" in text for text in progress.descriptions)

    def test_failed_partial_download_is_removed(self, tmp_path, monkeypatch):
        class BrokenResponse:
            headers = {"content-length": "10"}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                yield b"partial"
                raise OSError("connection lost")

        class FakeConsole:
            def print(self, *args, **kwargs):
                pass

        class FakeProgress:
            console = FakeConsole()

            def reset(self, task_id, **kwargs):
                pass

            def update(self, task_id, **kwargs):
                pass

            def advance(self, task_id, amount):
                pass

        calls = 0

        def fake_get(*args, **kwargs):
            nonlocal calls
            calls += 1
            return BrokenResponse()

        monkeypatch.setattr("patreon_download.downloader.requests.get", fake_get)
        monkeypatch.setattr("patreon_download.downloader.time.sleep", lambda delay: None)
        dest = tmp_path / "broken.png"

        ok = _download_file_progress(
            "https://example.com/broken.png",
            dest,
            "cookie",
            FakeProgress(),
            task_id=1,
            max_retries=3,
        )

        assert ok is False
        assert calls == 3
        assert not dest.exists()


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


class TestCancelEvent:
    """Test cancellation support for batch downloads."""

    def test_sequential_batch_raises_cancelled(self, tmp_path, monkeypatch):
        monkeypatch.setattr("patreon_download.downloader.requests.get", lambda *a, **kw: 1 / 0)
        tasks = [
            ("https://example.com/a.jpg", tmp_path / "a.jpg", "cookie"),
            ("https://example.com/b.jpg", tmp_path / "b.jpg", "cookie"),
        ]
        cancel_event = threading.Event()
        cancel_event.set()

        with pytest.raises(CancelledError):
            _download_batch_sequential(
                tasks, skip_existing=False, registry=None, max_retries=1,
                cancel_event=cancel_event,
            )

    def test_sequential_batch_without_event_runs(self, tmp_path, monkeypatch):
        class FakeResponse:
            headers = {"content-length": "4"}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                yield b"data"

        class FakeConsole:
            def print(self, *args, **kwargs):
                pass

        class FakeProgress:
            console = FakeConsole()

            def __init__(self):
                pass

            def reset(self, task_id, **kwargs):
                pass

            def update(self, task_id, **kwargs):
                pass

            def advance(self, task_id, amount):
                pass

        monkeypatch.setattr("patreon_download.downloader.requests.get", lambda *a, **kw: FakeResponse())
        tasks = [("https://example.com/a.jpg", tmp_path / "a.jpg", "cookie")]
        count = _download_batch_sequential(
            tasks, skip_existing=False, registry=None, max_retries=1,
        )
        assert count == 1
