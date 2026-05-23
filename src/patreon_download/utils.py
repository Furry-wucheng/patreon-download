from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qs, urlparse


def extract_post_id(url: str) -> str | None:
    """Extract post ID from a Patreon post URL."""
    match = re.search(r"/posts/(?:.+-)?(\d+)$", url)
    return match.group(1) if match else None


def extract_user_info(url: str) -> dict | None:
    """Extract user info from a Patreon creator URL.

    Returns:
        {'type': 'vanity', 'value': str} or {'type': 'user_id', 'value': str}
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    # Reject if not a real URL (no scheme and no path that looks like a patreon path)
    if not parsed.scheme and "patreon" not in url.lower():
        return None

    # Reject single post URLs: /posts/<id> or /posts/<slug>-<id>
    if re.search(r"/posts/(?:.+-)?\d+$", path):
        return None

    # /user/posts?u=<user_id>
    if "/user/posts" in path:
        params = parse_qs(parsed.query)
        user_id = params.get("u", [None])[0]
        if user_id:
            return {"type": "user_id", "value": user_id}

    # /<creator>/posts, /c/<creator>/posts, /cw/<creator>/posts
    match = re.search(r"(?:patreon\.com/(?:c|cw)/)?([^/]+)/posts$", f"{parsed.path}")
    if match:
        vanity = match.group(1)
        if vanity != "user":
            return {"type": "vanity", "value": vanity}

    # /<creator>/shop, /c/<creator>/shop
    match = re.search(r"(?:patreon\.com/(?:c|cw)/)?([^/]+)/shop$", f"{parsed.path}")
    if match:
        return {"type": "vanity", "value": match.group(1)}

    # Bare creator URL: /<creator> or /c/<creator>
    match = re.search(r"(?:patreon\.com/(?:c|cw)/)?([^/]+)$", path)
    if match:
        vanity = match.group(1)
        if vanity not in ("posts", "shop", "about", "c", "cw", "user"):
            return {"type": "vanity", "value": vanity}

    return None


def format_post_dirname(
    fmt: str,
    post_id: str,
    title: str = "",
    author: str = "",
    published_at: str | None = None,
) -> str:
    """Format a post directory name from a template string.

    Supported placeholders:
        {id}        — post ID
        {title}     — post title (auto-sanitized)
        {author}    — author name (auto-sanitized)
        {yyyy}      — 4-digit year
        {mm}        — 2-digit month
        {dd}        — 2-digit day
        {date}      — shorthand for {yyyy}-{mm}-{dd}

    Falls back to post ID if all date parts are missing.
    """
    # Parse date parts
    yyyy = mm = dd = ""
    if published_at:
        # Handles ISO formats like 2025-01-15T12:00:00.000+00:00
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})", published_at)
        if match:
            yyyy, mm, dd = match.group(1), match.group(2), match.group(3)

    result = fmt.format(
        id=post_id,
        title=sanitize_filename(title) if title else post_id,
        author=sanitize_filename(author) if author else "unknown",
        yyyy=yyyy,
        mm=mm,
        dd=dd,
        date=f"{yyyy}-{mm}-{dd}" if yyyy else "",
    )

    # Clean up leftover empty placeholders and excessive separators
    result = re.sub(r"\s+", " ", result).strip()
    result = re.sub(r"[_\-\s]{2,}", "_", result).strip("_- ")

    return sanitize_filename(result) if result else post_id


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Sanitize a string for use as a filename."""
    # Normalize unicode
    name = unicodedata.normalize("NFC", name)
    # Replace problematic characters
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    # Trim length
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name or "unnamed"
