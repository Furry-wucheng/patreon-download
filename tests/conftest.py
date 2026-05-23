"""Shared fixtures for all tests."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_config(tmp_path):
    """Create a temporary config.json and return its path."""
    config_data = {
        "cookie": "test_cookie_value",
        "output_dir": str(tmp_path / "downloads"),
        "request_delay": 0.0,
        "max_retries": 1,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    return config_path


@pytest.fixture
def sample_post_response():
    """A realistic mock of Patreon /api/posts/{id} response."""
    return {
        "data": {
            "id": "12345678",
            "type": "post",
            "attributes": {
                "title": "Test Post Title",
                "content": "<p>Hello world</p>",
                "published_at": "2025-01-15T12:00:00.000+00:00",
                "current_user_can_view": True,
                "post_type": "video_file",
                "post_file": {"url": "https://cdn.patreon.com/video.mp4"},
                "embed": None,
            },
            "relationships": {
                "images": {
                    "data": [
                        {"id": "img_001", "type": "media"},
                        {"id": "img_002", "type": "media"},
                    ]
                },
                "audio": {"data": None},
                "attachments_media": {
                    "data": [{"id": "att_001", "type": "media"}]
                },
                "campaign": {
                    "data": {"id": "camp_001", "type": "campaign"}
                },
            },
        },
        "included": [
            {
                "id": "camp_001",
                "type": "campaign",
                "attributes": {"name": "Test Creator"},
            },
            {
                "id": "img_001",
                "type": "media",
                "attributes": {
                    "media_type": "image",
                    "mimetype": "image/jpeg",
                    "image_urls": {
                        "original": "https://cdn.patreon.com/img001_original.jpg",
                        "default": "https://cdn.patreon.com/img001_default.jpg",
                    },
                    "file_name": "artwork_001.jpg",
                },
            },
            {
                "id": "img_002",
                "type": "media",
                "attributes": {
                    "media_type": "image",
                    "mimetype": "image/png",
                    "image_urls": {
                        "original": "https://cdn.patreon.com/img002_original.png",
                    },
                    "file_name": "artwork_002.png",
                },
            },
            {
                "id": "att_001",
                "type": "media",
                "attributes": {
                    "media_type": "file",
                    "mimetype": "application/zip",
                    "download_url": "https://cdn.patreon.com/attachment.zip",
                    "file_name": "source_files.zip",
                    "owner_relationship": "attachment",
                },
            },
        ],
    }


@pytest.fixture
def sample_post_list_response():
    """A mock of Patreon /api/posts list response with 2 posts."""
    return {
        "data": [
            {
                "id": "11111111",
                "type": "post",
                "attributes": {
                    "title": "First Post",
                    "content": "Content 1",
                    "published_at": "2025-01-10T00:00:00Z",
                    "current_user_can_view": True,
                },
                "relationships": {
                    "images": {"data": []},
                    "audio": {"data": None},
                    "attachments_media": {"data": []},
                },
            },
            {
                "id": "22222222",
                "type": "post",
                "attributes": {
                    "title": "Second Post",
                    "content": "Content 2",
                    "published_at": "2025-01-05T00:00:00Z",
                    "current_user_can_view": False,
                },
                "relationships": {
                    "images": {"data": []},
                    "audio": {"data": None},
                    "attachments_media": {"data": []},
                },
            },
        ],
        "included": [],
        "meta": {"pagination": {"total": 2}},
        "links": {},
    }


@pytest.fixture
def sample_product_response():
    """A mock of Patreon /api/campaigns/{id}/products response."""
    return {
        "data": [
            {
                "id": "prod_001",
                "type": "product",
                "attributes": {},
                "relationships": {
                    "product-variant": {
                        "data": [{"id": "var_001", "type": "product-variant"}]
                    },
                    "preview_media": {
                        "data": [{"id": "prev_001", "type": "media"}]
                    },
                    "content_media": {"data": []},
                },
            },
        ],
        "included": [
            {
                "id": "var_001",
                "type": "product-variant",
                "attributes": {
                    "name": "Wallpaper Pack",
                    "description": "High-res wallpapers",
                    "price_cents": 500,
                    "currency_code": "USD",
                    "url": "https://www.patreon.com/shop/wallpaper-pack",
                    "content_type": "digital_commerce",
                    "published_at_datetime": "2025-02-01T00:00:00Z",
                    "access_metadata": {"is_accessible": True},
                },
            },
            {
                "id": "prev_001",
                "type": "media",
                "attributes": {
                    "media_type": "image",
                    "mimetype": "image/jpeg",
                    "image_urls": {
                        "original": "https://cdn.patreon.com/preview.jpg",
                    },
                    "file_name": "preview.jpg",
                },
            },
        ],
        "links": {},
    }
