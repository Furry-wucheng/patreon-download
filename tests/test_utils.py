"""Tests for utils.py — URL parsing and filename helpers."""

import pytest

from patreon_download.utils import (
    extract_post_id,
    extract_user_info,
    format_post_dirname,
    parse_date,
    published_in_range,
    sanitize_filename,
)


# ── extract_post_id ──────────────────────────────────────────────

class TestExtractPostId:
    """Test post ID extraction from various URL formats."""

    @pytest.mark.parametrize("url,expected", [
        ("https://www.patreon.com/posts/12345678", "12345678"),
        ("https://www.patreon.com/posts/my-cool-post-99999", "99999"),
        ("https://www.patreon.com/posts/slug-with-dashes-42", "42"),
        ("https://www.patreon.com/posts/123", "123"),
    ], ids=[
        "numeric_only",
        "slug_with_id",
        "slug_with_multiple_dashes",
        "short_id",
    ])
    def test_valid_urls(self, url, expected):
        result = extract_post_id(url)
        assert result == expected, f"Expected {expected!r} from {url}, got {result!r}"

    @pytest.mark.parametrize("url", [
        "https://www.patreon.com/creator/posts",
        "https://www.patreon.com/",
        "not a url",
        "",
        "https://www.patreon.com/posts/",
    ], ids=[
        "user_posts_page",
        "root_url",
        "garbage",
        "empty",
        "posts_no_id",
    ])
    def test_invalid_urls(self, url):
        result = extract_post_id(url)
        assert result is None, f"Expected None from {url!r}, got {result!r}"


# ── extract_user_info ────────────────────────────────────────────

class TestExtractUserInfo:
    """Test user/creator info extraction from various URL formats."""

    @pytest.mark.parametrize("url,expected_type,expected_value", [
        ("https://www.patreon.com/creator/posts", "vanity", "creator"),
        ("https://www.patreon.com/c/creator/posts", "vanity", "creator"),
        ("https://www.patreon.com/cw/creator/posts", "vanity", "creator"),
        ("https://www.patreon.com/creator/shop", "vanity", "creator"),
        ("https://www.patreon.com/c/creator/shop", "vanity", "creator"),
        ("https://www.patreon.com/user/posts?u=12345", "user_id", "12345"),
    ], ids=[
        "vanity_posts",
        "c_prefix_posts",
        "cw_prefix_posts",
        "vanity_shop",
        "c_prefix_shop",
        "user_id_query",
    ])
    def test_valid_urls(self, url, expected_type, expected_value):
        result = extract_user_info(url)
        assert result is not None, f"Got None from {url!r}"
        assert result["type"] == expected_type, f"Expected type {expected_type!r}, got {result['type']!r}"
        assert result["value"] == expected_value, f"Expected value {expected_value!r}, got {result['value']!r}"

    @pytest.mark.parametrize("url", [
        "https://www.patreon.com/posts/12345678",
        "",
        "not a url",
    ], ids=[
        "single_post_url",
        "empty",
        "garbage",
    ])
    def test_invalid_urls(self, url):
        result = extract_user_info(url)
        assert result is None, f"Expected None from {url!r}, got {result!r}"


# ── sanitize_filename ────────────────────────────────────────────

class TestSanitizeFilename:
    """Test filename sanitization."""

    @pytest.mark.parametrize("input_name,expected", [
        ("hello.jpg", "hello.jpg"),
        ("my file (1).png", "my file (1).png"),
        ('file<>:"/\\|?*.txt', "file_________.txt"),
        ("  spaces  ", "spaces"),
        ("a" * 300, "a" * 200),
        ("", "unnamed"),
    ], ids=[
        "normal",
        "spaces_and_parens",
        "illegal_chars",
        "leading_trailing_spaces",
        "too_long",
        "empty",
    ])
    def test_sanitize(self, input_name, expected):
        result = sanitize_filename(input_name)
        assert result == expected, f"sanitize_filename({input_name!r}) = {result!r}, expected {expected!r}"


# ── format_post_dirname ──────────────────────────────────────────

class TestFormatPostDirname:
    """Test post directory name formatting."""

    def test_default_format(self):
        result = format_post_dirname(
            "{yyyy}-{mm}-{dd}_{title}",
            post_id="12345",
            title="My Art",
            published_at="2025-03-20T10:00:00Z",
        )
        assert result == "2025-03-20_My Art"

    def test_all_placeholders(self):
        result = format_post_dirname(
            "{yyyy}{mm}{dd}-{author}-{title}-{id}",
            post_id="99",
            title="Cool Post",
            author="Artist Name",
            published_at="2024-12-01T00:00:00Z",
        )
        assert result == "20241201-Artist Name-Cool Post-99"

    def test_date_only(self):
        result = format_post_dirname(
            "{date}",
            post_id="1",
            published_at="2025-06-15T08:30:00Z",
        )
        assert result == "2025-06-15"

    def test_no_date_fallback(self):
        result = format_post_dirname(
            "{yyyy}-{mm}-{dd}_{title}",
            post_id="42",
            title="No Date Post",
            published_at=None,
        )
        assert result == "No Date Post"

    def test_id_only(self):
        result = format_post_dirname(
            "post_{id}",
            post_id="12345",
            title="Ignored",
        )
        assert result == "post_12345"

    def test_title_with_special_chars(self):
        result = format_post_dirname(
            "{title}",
            post_id="1",
            title='File<>:"bad?.jpg',
        )
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result

    def test_empty_title_uses_id(self):
        result = format_post_dirname(
            "{title}",
            post_id="555",
            title="",
        )
        assert result == "555"

    def test_chinese_title(self):
        result = format_post_dirname(
            "{yyyy}-{mm}-{dd}_{title}",
            post_id="1",
            title="测试作品",
            published_at="2025-01-01T00:00:00Z",
        )
        assert result == "2025-01-01_测试作品"


# ── parse_date ───────────────────────────────────────────────────

class TestParseDate:
    """Test date parsing for time-range filtering."""

    def test_basic_date(self):
        assert parse_date("2025-01-15") is not None
        assert parse_date("2025-01-15").isoformat() == "2025-01-15"

    def test_iso_datetime(self):
        d = parse_date("2025-01-15T12:00:00.000+00:00")
        assert d is not None
        assert d.isoformat() == "2025-01-15"

    def test_iso_short(self):
        d = parse_date("2025-01-15T00:00:00Z")
        assert d is not None
        assert d.isoformat() == "2025-01-15"

    def test_empty_returns_none(self):
        assert parse_date("") is None
        assert parse_date(None) is None

    @pytest.mark.parametrize("value", [
        "2025-13-01",   # 月份越界
        "2025-02-30",   # 日期越界
        "15/01/2025",   # 格式错误
        "hello",        # 非日期
        "2025-01",      # 缺少日期
    ])
    def test_invalid_returns_none(self, value):
        assert parse_date(value) is None

    def test_whitespace_stripped(self):
        assert parse_date("  2025-01-15  ") is not None


# ── published_in_range ───────────────────────────────────────────

class TestPublishedInRange:
    """Test date-range filtering of published_at timestamps."""

    def test_no_filter_keeps_everything(self):
        assert published_in_range("2025-01-15T00:00:00Z", "", "") is True

    def test_within_range(self):
        assert published_in_range("2025-06-15T00:00:00Z", "2025-01-01", "2025-12-31") is True

    def test_before_range(self):
        assert published_in_range("2024-12-31T00:00:00Z", "2025-01-01", "") is False

    def test_after_range(self):
        assert published_in_range("2026-01-01T00:00:00Z", "", "2025-12-31") is False

    def test_inclusive_bounds(self):
        assert published_in_range("2025-01-01T00:00:00Z", "2025-01-01", "2025-12-31") is True
        assert published_in_range("2025-12-31T23:59:59Z", "2025-01-01", "2025-12-31") is True

    def test_from_only(self):
        assert published_in_range("2025-06-15T00:00:00Z", "2025-01-01", "") is True
        assert published_in_range("2024-12-31T00:00:00Z", "2025-01-01", "") is False

    def test_to_only(self):
        assert published_in_range("2025-06-15T00:00:00Z", "", "2025-12-31") is True
        assert published_in_range("2026-01-01T00:00:00Z", "", "2025-12-31") is False

    def test_missing_date_kept(self):
        """无法判断日期的帖子在过滤时保留，避免误删。"""
        assert published_in_range(None, "2025-01-01", "2025-12-31") is True

    def test_unparseable_date_kept(self):
        assert published_in_range("not-a-date", "2025-01-01", "2025-12-31") is True
