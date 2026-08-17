"""Tests for api.py — API client and response parsing."""

import pytest

from patreon_download.api import PatreonClient, _find_included, _parse_media_item, _safe_get
from patreon_download.config import Config
from patreon_download.models import MediaItem, Post, Product


# ── Helper functions ─────────────────────────────────────────────

class TestSafeGet:
    """Test the _safe_get nested dict accessor."""

    def test_simple_path(self):
        assert _safe_get({"a": {"b": 1}}, "a", "b") == 1

    def test_none_intermediate_returns_default(self):
        assert _safe_get({"a": None}, "a", "b") is None

    def test_none_intermediate_with_custom_default(self):
        assert _safe_get({"a": None}, "a", "b", default={}) == {}

    def test_missing_key_returns_default(self):
        assert _safe_get({}, "a", "b", default="fallback") == "fallback"

    def test_non_dict_intermediate(self):
        assert _safe_get({"a": "string"}, "a", "b") is None

    def test_empty_keys_returns_input(self):
        assert _safe_get({"x": 1}) == {"x": 1}

    def test_deeply_nested_none(self):
        data = {"a": {"b": {"c": None}}}
        assert _safe_get(data, "a", "b", "c", "d") is None


class TestFindIncluded:
    """Test the _find_included helper."""

    def test_finds_matching_item(self):
        included = [
            {"id": "1", "type": "media", "attributes": {"name": "a"}},
            {"id": "2", "type": "media", "attributes": {"name": "b"}},
        ]
        result = _find_included(included, "2", "media")
        assert result is not None
        assert result["attributes"]["name"] == "b"

    def test_returns_none_when_not_found(self):
        included = [{"id": "1", "type": "media"}]
        assert _find_included(included, "999", "media") is None

    def test_type_mismatch_returns_none(self):
        included = [{"id": "1", "type": "media"}]
        assert _find_included(included, "1", "post") is None


class TestParseMediaItem:
    """Test _parse_media_item for different media types."""

    def test_image(self):
        data = {
            "id": "img1",
            "attributes": {
                "media_type": "image",
                "mimetype": "image/jpeg",
                "image_urls": {"original": "https://cdn.example.com/img.jpg"},
                "file_name": "photo.jpg",
            },
        }
        item = _parse_media_item(data)
        assert item.id == "img1"
        assert item.media_type == "image"
        assert item.url == "https://cdn.example.com/img.jpg"
        assert item.filename == "photo.jpg"

    def test_video(self):
        data = {
            "id": "vid1",
            "attributes": {
                "media_type": "video",
                "mimetype": "video/mp4",
                "display": {"url": "https://cdn.example.com/vid.mp4"},
            },
        }
        item = _parse_media_item(data)
        assert item.media_type == "video"
        assert item.url == "https://cdn.example.com/vid.mp4"

    def test_audio(self):
        data = {
            "id": "aud1",
            "attributes": {
                "media_type": "audio",
                "mimetype": "audio/mp3",
                "image_urls": {"original": "https://cdn.example.com/aud.mp3"},
            },
        }
        item = _parse_media_item(data)
        assert item.media_type == "audio"
        assert item.url == "https://cdn.example.com/aud.mp3"

    def test_attachment(self):
        data = {
            "id": "att1",
            "attributes": {
                "media_type": "file",
                "mimetype": "application/zip",
                "download_url": "https://cdn.example.com/file.zip",
                "owner_relationship": "attachment",
            },
        }
        item = _parse_media_item(data)
        assert item.media_type == "attachment"
        assert item.url == "https://cdn.example.com/file.zip"


# ── Post parsing ─────────────────────────────────────────────────

class TestInitialData:
    """Test creator metadata extraction from Patreon HTML."""

    def test_streaming_campaign_url_does_not_include_json_escape(self, monkeypatch):
        class FakeResponse:
            status_code = 200
            text = (
                r'<script>"campaign":"https://www.patreon.com/api/campaigns/'
                r'6876649\"}},"member":null</script>'
            )

        client = PatreonClient(Config())
        monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: FakeResponse())

        result = client.get_initial_data("jumperbear")

        assert result["campaign_id"] == "6876649"


class TestParsePost:
    """Test full post parsing from API response."""

    def test_parse_post_basic_fields(self, sample_post_response):
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(sample_post_response)

        assert isinstance(post, Post)
        assert post.id == "12345678"
        assert post.title == "Test Post Title"
        assert post.content == "<p>Hello world</p>"
        assert post.is_viewable is True
        assert post.published_at == "2025-01-15T12:00:00.000+00:00"

    def test_parse_post_images(self, sample_post_response):
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(sample_post_response)

        assert len(post.images) == 2
        assert post.images[0].id == "img_001"
        assert post.images[0].url == "https://cdn.patreon.com/img001_original.jpg"
        assert post.images[0].filename == "artwork_001.jpg"
        assert post.images[1].id == "img_002"
        assert post.images[1].url == "https://cdn.patreon.com/img002_original.png"

    def test_parse_post_video(self, sample_post_response):
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(sample_post_response)

        assert post.video is not None
        assert post.video.url == "https://cdn.patreon.com/video.mp4"
        assert post.video.media_type == "video"

    def test_parse_post_attachments(self, sample_post_response):
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(sample_post_response)

        assert len(post.attachments) == 1
        assert post.attachments[0].url == "https://cdn.patreon.com/attachment.zip"
        assert post.attachments[0].filename == "source_files.zip"

    def test_parse_post_no_audio(self, sample_post_response):
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(sample_post_response)

        assert post.audio is None

    def test_parse_post_author_name(self, sample_post_response):
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(sample_post_response)

        assert post.author_name == "Test Creator"

    def test_parse_post_no_campaign(self):
        """Post without campaign relationship has empty author_name."""
        minimal = {
            "data": {
                "id": "999",
                "type": "post",
                "attributes": {"title": "No Campaign"},
                "relationships": {},
            },
            "included": [],
        }
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(minimal)

        assert post.author_name == ""

    def test_parse_post_null_relationships(self):
        """Post with null relationship values (Patreon API quirk)."""
        data = {
            "data": {
                "id": "777",
                "type": "post",
                "attributes": {
                    "title": "Null Rels",
                    "post_metadata": None,
                    "embed": None,
                    "post_file": None,
                },
                "relationships": {
                    "images": None,
                    "audio": None,
                    "attachments_media": None,
                    "campaign": None,
                },
            },
            "included": [],
        }
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(data)

        assert post.id == "777"
        assert post.title == "Null Rels"
        assert post.images == []
        assert post.audio is None
        assert post.video is None
        assert post.attachments == []
        assert post.author_name == ""

    def test_parse_post_non_video_post_file_ignored(self):
        """post_file with non-video post_type should NOT create a video item."""
        data = {
            "data": {
                "id": "555",
                "type": "post",
                "attributes": {
                    "title": "Image Post",
                    "post_type": "image_file",
                    "post_file": {"url": "https://cdn.patreon.com/thumb.jpg"},
                },
                "relationships": {
                    "images": {"data": []},
                    "audio": {"data": None},
                    "attachments_media": {"data": []},
                },
            },
            "included": [],
        }
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(data)

        assert post.video is None

    def test_parse_post_video_by_extension(self):
        """post_file with .mp4 URL should be detected as video even without post_type."""
        data = {
            "data": {
                "id": "666",
                "type": "post",
                "attributes": {
                    "title": "Video by Extension",
                    "post_file": {"url": "https://cdn.patreon.com/clip.mp4"},
                },
                "relationships": {
                    "images": {"data": []},
                    "audio": {"data": None},
                    "attachments_media": {"data": []},
                },
            },
            "included": [],
        }
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(data)

        assert post.video is not None
        assert post.video.url == "https://cdn.patreon.com/clip.mp4"

    def test_parse_post_minimal(self):
        """Test parsing a post with minimal data."""
        minimal = {
            "data": {
                "id": "999",
                "type": "post",
                "attributes": {},
                "relationships": {},
            },
            "included": [],
        }
        config = Config(cookie="test")
        client = PatreonClient(config)
        post = client._parse_post(minimal)

        assert post.id == "999"
        assert post.title == ""
        assert post.images == []
        assert post.audio is None
        assert post.video is None
        assert post.attachments == []


# ── Post list parsing ────────────────────────────────────────────

class TestParsePostList:
    """Test post list response parsing."""

    def test_parse_list_count(self, sample_post_list_response):
        config = Config(cookie="test")
        client = PatreonClient(config)

        data_list = sample_post_list_response["data"]
        included = sample_post_list_response["included"]

        posts = []
        for item in data_list:
            if item.get("type") == "post":
                post_json = {"data": item, "included": included}
                posts.append(client._parse_post(post_json))

        assert len(posts) == 2
        assert posts[0].id == "11111111"
        assert posts[0].title == "First Post"
        assert posts[1].id == "22222222"
        assert posts[1].title == "Second Post"

    def test_parse_list_viewable_flag(self, sample_post_list_response):
        config = Config(cookie="test")
        client = PatreonClient(config)

        posts = []
        for item in sample_post_list_response["data"]:
            if item.get("type") == "post":
                posts.append(client._parse_post({"data": item, "included": []}))

        assert posts[0].is_viewable is True
        assert posts[1].is_viewable is False


# ── Product parsing ──────────────────────────────────────────────

class TestParseProduct:
    """Test product parsing from shop API response."""

    def test_parse_product_basic(self, sample_product_response):
        config = Config(cookie="test")
        client = PatreonClient(config)

        product_data = sample_product_response["data"][0]
        product = client._parse_product(sample_product_response, product_data)

        assert isinstance(product, Product)
        assert product.id == "prod_001"
        assert product.name == "Wallpaper Pack"
        assert product.description == "High-res wallpapers"
        assert product.price_cents == 500
        assert product.currency_code == "USD"
        assert product.product_type == "digital_commerce"
        assert product.is_accessible is True

    def test_parse_product_preview_media(self, sample_product_response):
        config = Config(cookie="test")
        client = PatreonClient(config)

        product_data = sample_product_response["data"][0]
        product = client._parse_product(sample_product_response, product_data)

        assert len(product.preview_media) == 1
        assert product.preview_media[0].media_type == "image"
        assert product.preview_media[0].url == "https://cdn.patreon.com/preview.jpg"

    def test_parse_product_no_content_media(self, sample_product_response):
        config = Config(cookie="test")
        client = PatreonClient(config)

        product_data = sample_product_response["data"][0]
        product = client._parse_product(sample_product_response, product_data)

        assert product.content_media == []


# ── Date range filtering ─────────────────────────────────────────

def _post_item(post_id: str, published_at: str) -> dict:
    return {
        "id": post_id,
        "type": "post",
        "attributes": {"title": f"Post {post_id}", "published_at": published_at},
        "relationships": {
            "images": {"data": []},
            "audio": {"data": None},
            "attachments_media": {"data": []},
        },
    }


class TestFetchAllPostsDateFilter:
    """Test time-range filtering and early-stop pagination."""

    def _client_with_pages(self, monkeypatch, pages, config=None):
        client = PatreonClient(config or Config(cookie="test"))
        calls = {"count": 0}

        def fake_get(url, params=None, delay=True):
            calls["count"] += 1
            return pages[min(calls["count"], len(pages)) - 1]

        monkeypatch.setattr(client, "_get", fake_get)
        return client, calls

    def test_filter_in_range_keeps_matching_posts(self, monkeypatch):
        page1 = {
            "data": [
                _post_item("1", "2025-01-10T00:00:00Z"),
                _post_item("2", "2025-01-05T00:00:00Z"),
            ],
            "included": [],
            "meta": {"pagination": {"total": 4}},
            "links": {"next": "https://api/next"},
        }
        page2 = {
            "data": [
                _post_item("3", "2024-12-20T00:00:00Z"),
                _post_item("4", "2024-11-01T00:00:00Z"),
            ],
            "included": [],
            "meta": {"pagination": {"total": 4}},
            "links": {},
        }
        config = Config(cookie="test", date_from="2025-01-01")
        client, calls = self._client_with_pages(monkeypatch, [page1, page2], config)

        posts = client.fetch_all_posts("camp_1", "user_1")

        # 页面 2 整页早于 date_from → 早停；页面 1 内帖子全部保留
        assert calls["count"] == 2
        assert [p.id for p in posts] == ["1", "2"]

    def test_early_stop_skips_older_pages(self, monkeypatch):
        page1 = {
            "data": [
                _post_item("1", "2025-01-10T00:00:00Z"),
                _post_item("2", "2025-01-05T00:00:00Z"),
            ],
            "included": [],
            "meta": {"pagination": {"total": 4}},
            "links": {"next": "https://api/next"},
        }
        page2 = {
            "data": [_post_item("3", "2024-12-20T00:00:00Z")],
            "included": [],
            "meta": {"pagination": {"total": 4}},
            "links": {},
        }
        config = Config(cookie="test", date_from="2025-02-01")
        client, calls = self._client_with_pages(monkeypatch, [page1, page2], config)

        posts = client.fetch_all_posts("camp_1", "user_1")

        # 第 1 页整页早于 date_from → 不再请求第 2 页
        assert calls["count"] == 1
        assert posts == []

    def test_filter_without_early_stop_when_page_overlaps(self, monkeypatch):
        page1 = {
            "data": [
                _post_item("1", "2025-01-10T00:00:00Z"),
                _post_item("2", "2025-01-05T00:00:00Z"),
            ],
            "included": [],
            "meta": {"pagination": {"total": 4}},
            "links": {"next": "https://api/next"},
        }
        page2 = {
            "data": [
                _post_item("3", "2024-12-20T00:00:00Z"),
                _post_item("4", "2024-11-01T00:00:00Z"),
            ],
            "included": [],
            "meta": {"pagination": {"total": 4}},
            "links": {},
        }
        config = Config(cookie="test", date_from="2024-12-01")
        client, calls = self._client_with_pages(monkeypatch, [page1, page2], config)

        posts = client.fetch_all_posts("camp_1", "user_1")

        assert calls["count"] == 2
        assert [p.id for p in posts] == ["1", "2", "3"]

    def test_filter_date_to(self, monkeypatch):
        page1 = {
            "data": [_post_item("1", "2025-01-10T00:00:00Z")],
            "included": [],
            "meta": {"pagination": {"total": 2}},
            "links": {"next": "https://api/next"},
        }
        page2 = {
            "data": [_post_item("2", "2024-12-01T00:00:00Z")],
            "included": [],
            "meta": {"pagination": {"total": 2}},
            "links": {},
        }
        config = Config(cookie="test", date_to="2025-01-05")
        client, calls = self._client_with_pages(monkeypatch, [page1, page2], config)

        posts = client.fetch_all_posts("camp_1", "user_1")

        assert calls["count"] == 2  # date_to 不触发早停
        assert [p.id for p in posts] == ["2"]

    def test_no_early_stop_when_page_has_undated_post(self, monkeypatch):
        undated = _post_item("2", "2025-01-05T00:00:00Z")
        undated["attributes"]["published_at"] = None
        page1 = {
            "data": [_post_item("1", "2025-01-10T00:00:00Z"), undated],
            "included": [],
            "meta": {"pagination": {"total": 3}},
            "links": {"next": "https://api/next"},
        }
        page2 = {
            "data": [_post_item("3", "2024-11-01T00:00:00Z")],
            "included": [],
            "meta": {"pagination": {"total": 3}},
            "links": {},
        }
        config = Config(cookie="test", date_from="2025-01-01")
        client, calls = self._client_with_pages(monkeypatch, [page1, page2], config)

        posts = client.fetch_all_posts("camp_1", "user_1")

        # 页面存在无日期帖子 → 不早停；无日期帖子保留
        assert calls["count"] == 2
        assert [p.id for p in posts] == ["1", "2"]

    def test_no_filter_fetches_all(self, monkeypatch):
        page1 = {
            "data": [_post_item("1", "2025-01-10T00:00:00Z")],
            "included": [],
            "meta": {"pagination": {"total": 2}},
            "links": {"next": "https://api/next"},
        }
        page2 = {
            "data": [_post_item("2", "2024-12-01T00:00:00Z")],
            "included": [],
            "meta": {"pagination": {"total": 2}},
            "links": {},
        }
        client, calls = self._client_with_pages(monkeypatch, [page1, page2])

        posts = client.fetch_all_posts("camp_1", "user_1")

        assert calls["count"] == 2
        assert [p.id for p in posts] == ["1", "2"]


class TestFetchAllProductsDateFilter:
    """Test time-range filtering for shop products."""

    def test_products_filtered_by_date(self, monkeypatch):
        product1 = {
            "id": "prod_001",
            "type": "product",
            "attributes": {},
            "relationships": {
                "product-variant": {
                    "data": [{"id": "var_001", "type": "product-variant"}]
                },
                "preview_media": {"data": []},
                "content_media": {"data": []},
            },
        }
        product2 = {
            "id": "prod_002",
            "type": "product",
            "attributes": {},
            "relationships": {
                "product-variant": {
                    "data": [{"id": "var_002", "type": "product-variant"}]
                },
                "preview_media": {"data": []},
                "content_media": {"data": []},
            },
        }
        response = {
            "data": [product1, product2],
            "included": [
                {
                    "id": "var_001",
                    "type": "product-variant",
                    "attributes": {
                        "name": "New Pack",
                        "published_at_datetime": "2025-06-01T00:00:00Z",
                    },
                },
                {
                    "id": "var_002",
                    "type": "product-variant",
                    "attributes": {
                        "name": "Old Pack",
                        "published_at_datetime": "2024-03-01T00:00:00Z",
                    },
                },
            ],
            "links": {},
        }
        config = Config(cookie="test", date_from="2025-01-01", date_to="2025-12-31")
        client = PatreonClient(config)
        calls = {"count": 0}
        monkeypatch.setattr(client, "_get", lambda *a, **kw: response)

        products = client.fetch_all_products("camp_1")

        assert [p.id for p in products] == ["prod_001"]
        assert products[0].name == "New Pack"
