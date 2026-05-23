"""Tests for utils.py — URL parsing and filename helpers."""

import pytest

from patreon_download.utils import extract_post_id, extract_user_info, format_post_dirname, sanitize_filename


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
