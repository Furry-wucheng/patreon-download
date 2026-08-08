from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from rich.console import Console
from rich.progress import (
    Progress, DownloadColumn, TransferSpeedColumn,
    TimeRemainingColumn, BarColumn, TextColumn, TaskID,
)

from .config import Config
from .models import MediaItem, Post, Product
from .utils import format_post_dirname, sanitize_filename

console = Console()

_HASH_ALGO = "sha256"
_REGISTRY_NAME = ".hashes.json"


# ── Hash registry ────────────────────────────────────────────────

class HashRegistry:
    """Tracks file hashes for content-based deduplication.

    Registry file format (.hashes.json):
        { "<sha256>": "relative/path/to/file", ... }
    """

    def __init__(self, base_dir: Path) -> None:
        self._path = base_dir / _REGISTRY_NAME
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._path.is_file():
            try:
                with open(self._path, encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def save(self) -> None:
        with self._lock:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)

    def has_hash(self, file_hash: str) -> bool:
        with self._lock:
            return file_hash in self._data

    def get_path(self, file_hash: str) -> str | None:
        with self._lock:
            return self._data.get(file_hash)

    def register(self, file_hash: str, relative_path: str) -> None:
        with self._lock:
            self._data[file_hash] = relative_path


def _compute_hash(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.new(_HASH_ALGO)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


# ── Single file download ─────────────────────────────────────────

def _download_file(
    url: str, dest: Path, cookie: str, max_retries: int = 3,
) -> bool:
    """Download a single file, retrying failures. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(1, max_retries)
    for attempt in range(attempts):
        try:
            resp = requests.get(
                url,
                headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"},
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception:
            dest.unlink(missing_ok=True)
            if attempt < attempts - 1:
                time.sleep(min(2 ** attempt, 30))
    return False


def _download_file_progress(
    url: str, dest: Path, cookie: str,
    progress: Progress, task_id: TaskID,
    max_retries: int = 3,
) -> bool:
    """Download a file with visible retry and progress updates."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(1, max_retries)
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            progress.reset(
                task_id, total=None, completed=0,
                description=dest.name,
            )
            resp = requests.get(
                url,
                headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"},
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            progress.update(task_id, total=total or None)

            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    progress.advance(task_id, len(chunk))

            return True
        except Exception as exc:
            last_error = exc
            dest.unlink(missing_ok=True)
            if attempt < attempts - 1:
                delay = min(2 ** attempt, 30)
                progress.update(
                    task_id,
                    description=(
                        f"[yellow]{dest.name} RETRY "
                        f"{attempt + 2}/{attempts} in {delay}s[/yellow]"
                    ),
                    completed=0,
                    total=None,
                )
                time.sleep(delay)

    progress.update(
        task_id,
        description=f"[red]{dest.name} FAILED after {attempts} attempts[/red]",
        completed=0,
        total=None,
    )
    progress.console.print(
        f"  {dest.name} failed: {last_error}", style="red", markup=False,
    )
    return False


# ── Dedup logic ──────────────────────────────────────────────────

def _resolve_download(
    url: str, dest: Path, cookie: str,
    skip_existing: bool, registry: HashRegistry | None,
    max_retries: int = 3,
) -> tuple[bool, bool]:
    """Decide whether and how to get a file.

    Returns:
        (downloaded, skipped) — exactly one is True.
    """
    if not skip_existing:
        # Always download, overwrite existing
        return _download_file(url, dest, cookie, max_retries), False

    # ── Skip-existing mode ───────────────────────────────────────

    if dest.is_file() and registry:
        # File exists — verify content hash
        actual_hash = _compute_hash(dest)
        known_path = registry.get_path(actual_hash)
        if known_path:
            # Hash is registered — file is intact
            relative = str(dest.relative_to(dest.parents[len(dest.parts) - 2]) if len(dest.parts) > 1 else dest)
            if known_path == relative or Path(known_path).exists():
                return False, True

    if dest.is_file() and not registry:
        # No registry, simple existence check
        return False, True

    # File doesn't exist — check if content is already elsewhere
    if registry:
        # We don't know the hash yet (haven't downloaded), so just download
        pass

    ok = _download_file(url, dest, cookie, max_retries)

    # Register hash after successful download
    if ok and registry:
        file_hash = _compute_hash(dest)
        # Store relative path from base_dir (parent of .hashes.json)
        base = registry._path.parent
        try:
            relative = str(dest.relative_to(base))
        except ValueError:
            relative = dest.name
        registry.register(file_hash, relative)

    return ok, False


def _resolve_download_progress(
    url: str, dest: Path, cookie: str,
    progress: Progress, task_id: TaskID,
    skip_existing: bool, registry: HashRegistry | None,
    max_retries: int = 3,
) -> tuple[bool, bool]:
    """Same as _resolve_download but with progress bar."""
    if not skip_existing:
        ok = _download_file_progress(
            url, dest, cookie, progress, task_id, max_retries,
        )
        return ok, False

    if dest.is_file():
        size = _file_size(dest)
        progress.update(
            task_id,
            description=f"[dim]{dest.name} (exists, {_human_size(size)})[/dim]",
            completed=1, total=1,
        )
        return False, True

    ok = _download_file_progress(
        url, dest, cookie, progress, task_id, max_retries,
    )

    if ok and registry:
        file_hash = _compute_hash(dest)
        base = registry._path.parent
        try:
            relative = str(dest.relative_to(base))
        except ValueError:
            relative = dest.name
        registry.register(file_hash, relative)

    return ok, False


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# ── Batch download helpers ───────────────────────────────────────

def _collect_tasks(
    items: list[MediaItem], dest_dir: Path, cookie: str,
    subdir: str | None = None, skip_existing: bool = True,
) -> tuple[list[tuple[str, Path, str]], int]:
    """Collect download tasks. Returns (tasks, skipped_count)."""
    tasks = []
    skipped = 0
    for item in items:
        if not item.url:
            continue
        folder = dest_dir / subdir if subdir else dest_dir
        filename = sanitize_filename(item.filename or f"{item.id}")
        dest = folder / filename
        if skip_existing and dest.is_file():
            skipped += 1
        else:
            tasks.append((item.url, dest, cookie))
    return tasks, skipped


_PROGRESS_COLUMNS = (
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    DownloadColumn(),
    TransferSpeedColumn(),
    TimeRemainingColumn(),
)


def _download_batch_sequential(
    tasks: list[tuple[str, Path, str]],
    skip_existing: bool, registry: HashRegistry | None,
    max_retries: int = 3,
) -> int:
    """Download files one by one with individual progress bars."""
    count = 0
    for url, dest, cookie in tasks:
        with Progress(
            *_PROGRESS_COLUMNS,
            console=console, transient=True,
        ) as progress:
            task_id = progress.add_task(dest.name, total=None)
            ok, _ = _resolve_download_progress(
                url, dest, cookie, progress, task_id, skip_existing, registry,
                max_retries,
            )
            if ok:
                count += 1
    return count


def _download_batch_threaded(
    tasks: list[tuple[str, Path, str]],
    max_workers: int,
    skip_existing: bool, registry: HashRegistry | None,
    max_retries: int = 3,
) -> int:
    """Download files concurrently with a shared progress display."""
    if not tasks:
        return 0

    count = 0
    lock = threading.Lock()

    with Progress(
        *_PROGRESS_COLUMNS,
        console=console,
    ) as progress:
        task_ids: dict[str, TaskID] = {}
        for url, dest, _ in tasks:
            task_ids[url] = progress.add_task(dest.name, total=None)

        def do_download(url: str, dest: Path, cookie: str) -> bool:
            tid = task_ids[url]
            ok, _ = _resolve_download_progress(
                url, dest, cookie, progress, tid, skip_existing, registry,
                max_retries,
            )
            if ok:
                with lock:
                    nonlocal count
                    count += 1
            return ok

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(do_download, url, dest, cookie)
                for url, dest, cookie in tasks
            ]
            for f in as_completed(futures):
                f.result()

    return count


def _download_media_items(
    items: list[MediaItem], dest_dir: Path, config: Config,
    subdir: str | None = None, registry: HashRegistry | None = None,
) -> int:
    """Download a list of media items. Uses threading if configured."""
    tasks, skipped = _collect_tasks(
        items, dest_dir, config.cookie, subdir, config.skip_existing,
    )

    if skipped:
        console.print(f"  [dim]{skipped} file(s) already exist, skipped[/dim]")

    if not tasks:
        return 0

    if config.enable_threading:
        return _download_batch_threaded(
            tasks, config.max_workers, config.skip_existing, registry,
            config.max_retries,
        )
    return _download_batch_sequential(
        tasks, config.skip_existing, registry, config.max_retries,
    )


# ── Post / Product download ──────────────────────────────────────

def download_post(
    post: Post,
    output_dir: Path,
    config: Config,
    author_name: str = "",
    use_author_dir: bool = True,
    registry: HashRegistry | None = None,
) -> int:
    """Download a single post and all its media. Returns download count."""
    author = author_name or post.author_name or "unknown"
    post_folder = format_post_dirname(
        config.post_dir_format,
        post_id=post.id,
        title=post.title,
        author=author,
        published_at=post.published_at,
    )
    if use_author_dir:
        post_dir = output_dir / sanitize_filename(author) / post_folder
    else:
        post_dir = output_dir / post_folder
    post_dir.mkdir(parents=True, exist_ok=True)

    if config.output_info_json:
        _save_json({
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "published_at": post.published_at,
            "is_viewable": post.is_viewable,
            "embed": post.embed,
        }, post_dir / "info.json")

    all_items: list[MediaItem] = list(post.images)
    if post.audio and post.audio.url:
        all_items.append(post.audio)
    if post.video and post.video.url:
        all_items.append(post.video)
    all_items.extend(post.attachments)

    return _download_media_items(all_items, post_dir, config, registry=registry)


def download_product(
    product: Product, output_dir: Path, config: Config,
    author_name: str = "", registry: HashRegistry | None = None,
) -> int:
    """Download a single shop product. Returns download count."""
    author = author_name or "unknown"
    prod_dir = output_dir / sanitize_filename(author) / "shop" / sanitize_filename(f"{product.name}_{product.id}")
    prod_dir.mkdir(parents=True, exist_ok=True)

    if config.output_info_json:
        _save_json({
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "price_cents": product.price_cents,
            "currency_code": product.currency_code,
            "url": product.url,
            "product_type": product.product_type,
            "is_accessible": product.is_accessible,
            "published_at": product.published_at,
        }, prod_dir / "info.json")

    count = 0
    count += _download_media_items(product.preview_media, prod_dir, config, "preview", registry=registry)
    count += _download_media_items(product.content_media, prod_dir, config, "content", registry=registry)
    return count


def _save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
