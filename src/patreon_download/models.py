from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MediaItem:
    id: str
    url: str | None
    filename: str | None = None
    media_type: str = "unknown"  # image, video, audio, attachment


@dataclass
class Post:
    id: str
    title: str = ""
    content: str = ""
    published_at: str | None = None
    author_name: str = ""
    is_viewable: bool = False
    images: list[MediaItem] = field(default_factory=list)
    audio: MediaItem | None = None
    video: MediaItem | None = None
    attachments: list[MediaItem] = field(default_factory=list)
    embed: dict | None = None


@dataclass
class Product:
    id: str
    name: str = ""
    description: str = ""
    price_cents: int = 0
    currency_code: str = ""
    url: str | None = None
    product_type: str = "digital_commerce"
    preview_media: list[MediaItem] = field(default_factory=list)
    content_media: list[MediaItem] = field(default_factory=list)
    is_accessible: bool = True
    published_at: str | None = None
