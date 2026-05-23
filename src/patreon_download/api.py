from __future__ import annotations

import json
import re
import time
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

import requests
from requests.exceptions import RequestException

from .config import Config
from .models import MediaItem, Post, Product

def _safe_get(d, *keys, default=None):
    """Safely traverse nested dicts, treating None values as missing."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_POST_INCLUDES = ",".join([
    "collections", "campaign", "access_rules", "access_rules.tier.null",
    "attachments_media", "audio", "audio_preview.null", "images", "media",
    "native_video_insights", "poll.choices",
    "poll.current_user_responses.user", "poll.current_user_responses.choice",
    "poll.current_user_responses.poll", "user", "user_defined_tags", "ti_checks",
])


def _find_included(included: list, item_id: str, item_type: str) -> dict | None:
    for item in included:
        if item.get("id") == item_id and item.get("type") == item_type:
            return item
    return None


def _parse_media_item(media_data: dict) -> MediaItem:
    attrs = media_data.get("attributes", {})
    media_type = attrs.get("media_type", "")
    mime_type = attrs.get("mimetype", "")

    url = None
    kind = "unknown"

    if media_type == "image" or mime_type.startswith("image/"):
        kind = "image"
        url = (
            attrs.get("image_urls", {}).get("original")
            or attrs.get("download_url")
            or attrs.get("image_urls", {}).get("default")
        )
    elif media_type == "video" or mime_type.startswith("video/"):
        kind = "video"
        url = attrs.get("display", {}).get("url") or attrs.get("download_url")
    elif media_type == "audio" or mime_type.startswith("audio/"):
        kind = "audio"
        url = (
            attrs.get("image_urls", {}).get("original")
            or attrs.get("image_urls", {}).get("default")
            or attrs.get("download_url")
        )
    elif media_type == "file" or attrs.get("owner_relationship") == "attachment":
        kind = "attachment"
        url = attrs.get("download_url")

    return MediaItem(
        id=media_data.get("id", ""),
        url=url,
        filename=attrs.get("file_name"),
        media_type=kind,
    )


class PatreonClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "Cookie": config.cookie,
            "Host": "www.patreon.com",
            "User-Agent": _USER_AGENT,
        })

    def _get(self, url: str, params: dict | None = None, delay: bool = True) -> dict:
        """Make a GET request with retry and rate limiting."""
        headers = {"Content-Type": "application/vnd.api+json"}
        for attempt in range(self.config.max_retries):
            try:
                resp = self.session.get(url, params=params, headers=headers)
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 2) * 5
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                if delay:
                    time.sleep(self.config.request_delay)
                return resp.json()
            except RequestException as e:
                if attempt < self.config.max_retries - 1:
                    wait = 2 ** attempt * 5
                    time.sleep(wait)
                else:
                    raise RuntimeError(f"Request failed after {self.config.max_retries} retries: {e}") from e
        return {}

    # ── Initial Data ──────────────────────────────────────────────

    def get_initial_data(self, vanity: str) -> dict:
        """Get campaignId, currentUserId, and authorName from a creator page."""
        url = f"https://www.patreon.com/{vanity}/posts"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        resp = self.session.get(url, headers=headers)
        html = resp.text
        http_status = resp.status_code

        campaign_id = None
        current_user_id = None
        author_name = vanity  # fallback

        # Method 1: window.patreon = {...}
        match = re.search(r"window\.patreon\s*=\s*({.+?});", html)
        if match:
            data = json.loads(match.group(1))
            campaign = _safe_get(data, "pageBootstrap", "campaign", "data", default={})
            campaign_id = campaign.get("id")
            name = _safe_get(campaign, "attributes", "name")
            if name:
                author_name = name
            current_user_id = _safe_get(data, "commonBootstrap", "currentUser", "data", "id")

        # Method 2: __NEXT_DATA__
        if not campaign_id:
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.+)</script>', html
            )
            if match:
                data = json.loads(match.group(1))
                bootstrap = _safe_get(data, "props", "pageProps", "bootstrapEnvelope", default={})
                campaign = _safe_get(bootstrap, "pageBootstrap", "campaign", "data", default={})
                campaign_id = campaign.get("id")
                name = _safe_get(campaign, "attributes", "name")
                if name:
                    author_name = name
                current_user_id = _safe_get(bootstrap, "commonBootstrap", "currentUser", "data", "id")

        # Method 3: Next.js streaming
        if not campaign_id:
            match = re.search(r"https://www\.patreon\.com/api/campaigns/(.+?)\"", html)
            if match:
                campaign_id = match.group(1)

        # Fallback: get current user from API
        if self.config.cookie and not current_user_id:
            current_user_id = self._get_current_user_id()

        return {
            "campaign_id": campaign_id,
            "current_user_id": current_user_id,
            "author_name": author_name,
            "http_status": http_status,
        }

    def _get_current_user_id(self) -> str | None:
        try:
            data = self._get(
                "https://www.patreon.com/api/current_user",
                params={
                    "include": "active_memberships.campaign",
                    "json-api-version": "1.0",
                    "json-api-use-default-includes": "false",
                },
                delay=False,
            )
            return data.get("data", {}).get("id")
        except Exception:
            return None

    # ── Single Post ───────────────────────────────────────────────

    def fetch_post(self, post_id: str) -> Post:
        """Fetch and parse a single post."""
        data = self._get(
            f"https://www.patreon.com/api/posts/{post_id}",
            params={"include": _POST_INCLUDES, "json-api-version": "1.0"},
            delay=False,
        )
        return self._parse_post(data)

    def _parse_post(self, json_data: dict) -> Post:
        data = json_data.get("data", {})
        included = json_data.get("included", [])
        attrs = data.get("attributes", {})
        rels = data.get("relationships", {})
        post_id = data.get("id", "")

        # Extract author name from campaign relationship
        author_name = ""
        campaign_ref = _safe_get(rels, "campaign", "data")
        if campaign_ref:
            campaign = _find_included(included, campaign_ref.get("id", ""), "campaign")
            if campaign:
                author_name = _safe_get(campaign, "attributes", "name", default="")

        post = Post(
            id=post_id,
            title=attrs.get("title", ""),
            content=attrs.get("content", ""),
            published_at=attrs.get("published_at"),
            author_name=author_name,
            is_viewable=attrs.get("current_user_can_view", False),
        )

        # Images
        for ref in _safe_get(rels, "images", "data", default=[]):
            img = _find_included(included, ref.get("id", ""), "media")
            if img:
                a = img.get("attributes", {})
                post.images.append(MediaItem(
                    id=ref.get("id", ""),
                    url=_safe_get(a, "image_urls", "original") or a.get("download_url"),
                    filename=a.get("file_name", f"{post_id}_{ref.get('id', '')}.jpg"),
                    media_type="image",
                ))

        # Audio
        audio_ref = _safe_get(rels, "audio", "data")
        if audio_ref:
            audio = _find_included(included, audio_ref.get("id", ""), "media")
            if audio:
                a = audio.get("attributes", {})
                url = (
                    _safe_get(a, "image_urls", "original")
                    or _safe_get(a, "image_urls", "default")
                    or a.get("download_url")
                )
                post.audio = MediaItem(
                    id=audio_ref.get("id", ""), url=url, media_type="audio"
                )

        # Video — only if post_type indicates video or URL has a video extension
        post_file = attrs.get("post_file") or {}
        post_type = attrs.get("post_type", "")
        if isinstance(post_file, dict) and post_file.get("url"):
            url = post_file.get("url", "")
            is_video = (
                post_type in ("video_file", "video_embed")
                or any(url.lower().endswith(ext) for ext in (".mp4", ".webm", ".mov", ".avi", ".mkv"))
            )
            if is_video:
                post.video = MediaItem(
                    id=f"post_{post_id}_video", url=url, media_type="video"
                )

        # Attachments
        for ref in _safe_get(rels, "attachments_media", "data", default=[]):
            att = _find_included(included, ref.get("id", ""), "media")
            if att:
                a = att.get("attributes", {})
                post.attachments.append(MediaItem(
                    id=ref.get("id", ""),
                    url=a.get("download_url"),
                    filename=a.get("file_name", f"attachment_{ref.get('id', '')}"),
                    media_type="attachment",
                ))

        # Embed
        embed = attrs.get("embed") or _safe_get(attrs, "post_metadata", "embed")
        if embed:
            post.embed = {
                "type": embed.get("type", "unknown"),
                "provider": embed.get("provider", "unknown"),
                "url": embed.get("url") or embed.get("html", ""),
            }

        return post

    # ── All Posts ─────────────────────────────────────────────────

    def fetch_all_posts(
        self, campaign_id: str, current_user_id: str | None, on_page=None
    ) -> list[Post]:
        """Fetch all posts for a campaign with auto-pagination."""
        all_posts: list[Post] = []
        next_url = None

        params = {
            "include": _POST_INCLUDES,
            "sort": "-published_at",
            "json-api-version": "1.0",
            "filter[contains_exclusive_posts]": "true",
            "filter[is_draft]": "false",
            "filter[campaign_id]": campaign_id,
        }
        if current_user_id:
            params["filter[accessible_by_user_id]"] = current_user_id

        while True:
            if next_url:
                json_data = self._get(next_url)
            else:
                json_data = self._get(
                    "https://www.patreon.com/api/posts", params=params
                )

            data_list = json_data.get("data") or []
            included = json_data.get("included") or []
            total = _safe_get(json_data, "meta", "pagination", "total", default=0) or 0

            for item in data_list:
                if item.get("type") == "post":
                    post_json = {"data": item, "included": included}
                    all_posts.append(self._parse_post(post_json))

            if on_page:
                on_page(len(all_posts), total)

            next_url = _safe_get(json_data, "links", "next")
            if not next_url:
                break

            # Rebuild next URL with cursor if needed
            next_cursor = _safe_get(json_data, "meta", "pagination", "cursors", "next")
            if next_cursor:
                parsed = urlparse(next_url)
                p = parse_qs(parsed.query)
                p["page[cursor]"] = [next_cursor]
                next_url = urlunparse(parsed._replace(query=urlencode(p, doseq=True)))

        return all_posts

    # ── Shop Products ─────────────────────────────────────────────

    def fetch_all_products(self, campaign_id: str, on_page=None) -> list[Product]:
        """Fetch all shop products for a campaign."""
        all_products: list[Product] = []
        offset = 0

        while True:
            json_data = self._get(
                f"https://www.patreon.com/api/campaigns/{campaign_id}/products",
                params=self._product_params(campaign_id, offset),
            )
            data_list = json_data.get("data") or []
            if not data_list:
                break

            for item in data_list:
                if item.get("type") == "product":
                    all_products.append(self._parse_product(json_data, item))

            if on_page:
                on_page(len(all_products))

            if not _safe_get(json_data, "links", "next"):
                break
            offset += 24

        return all_products

    def _product_params(self, campaign_id: str, offset: int) -> dict:
        return {
            "fields[product-variant]": ",".join([
                "name", "id", "price_cents", "checkout_url", "currency_code",
                "description", "description_rich_text", "is_hidden",
                "published_at_datetime", "url", "share_url", "access_metadata",
                "moderation_status", "reward_ids", "content_type", "is_featured",
            ]),
            "fields[post]": ",".join([
                "change_visibility_at", "comment_count", "content", "content_teaser_text",
                "image", "is_paid", "is_suspended", "moderation_status", "like_count",
                "media_file_duration_seconds", "post_file", "post_metadata", "post_type",
                "published_at", "thumbnail", "thumbnail_url", "title", "url",
                "current_user_can_view", "external_embed_domain", "teaser_text",
            ]),
            "fields[collection]": ",".join([
                "created_at", "description", "edited_at", "id", "moderation_status",
                "num_posts", "post_ids", "thumbnail", "title", "type",
            ]),
            "fields[primary-image]": ",".join([
                "image_icon", "image_small", "image_medium", "image_large",
                "primary_image_type", "alt_text",
            ]),
            "include": ",".join([
                "product-variant", "preview_media", "preview_media_no_fallback",
                "content_media", "content_media.custom_thumbnail_media",
                "post", "collection", "post.images", "post.embedv2", "post.video",
                "post.primary_image", "campaign", "access_rules",
                "access_rules.tier.null", "post.audio", "post.drop",
            ]),
            "filter[campaign_id]": campaign_id,
            "filter[is_hidden]": "active",
            "filter[include_suspended]": "false",
            "filter[include_featured]": "all_products",
            "page[offset]": str(offset),
            "page[count]": "24",
            "page[pageType]": "offset",
            "sort": "-published_at",
            "json-api-version": "1.0",
            "json-api-use-default-includes": "false",
        }

    def _parse_product(self, json_data: dict, product_data: dict) -> Product:
        included = json_data.get("included", [])
        attrs = product_data.get("attributes") or {}
        rels = product_data.get("relationships") or {}
        product_id = product_data.get("id", "")

        # Variant info
        variant_ref = _safe_get(rels, "product-variant", "data", default=[])
        variant_data = None
        if isinstance(variant_ref, list) and variant_ref:
            variant_data = _find_included(included, variant_ref[0].get("id", ""), "product-variant")
        elif isinstance(variant_ref, dict):
            variant_data = _find_included(included, variant_ref.get("id", ""), "product-variant")

        va = variant_data.get("attributes") or {} if variant_data else {}

        content_type = va.get("content_type") or attrs.get("content_type")
        product_type = "post" if content_type == "post" else (
            "collection" if content_type == "collection" else "digital_commerce"
        )

        product = Product(
            id=product_id,
            name=va.get("name", ""),
            description=va.get("description", ""),
            price_cents=va.get("price_cents", 0),
            currency_code=va.get("currency_code", ""),
            url=va.get("url") or attrs.get("url"),
            product_type=product_type,
            is_accessible=_safe_get(va, "access_metadata", "is_accessible", default=True),
            published_at=va.get("published_at_datetime"),
        )

        # Preview media
        for ref in self._ensure_list(_safe_get(rels, "preview_media", "data", default=[])):
            if ref:
                media = _find_included(included, ref.get("id", ""), "media")
                if media:
                    product.preview_media.append(_parse_media_item(media))

        # Content media
        for ref in self._ensure_list(_safe_get(rels, "content_media", "data", default=[])):
            if ref:
                media = _find_included(included, ref.get("id", ""), "media")
                if media:
                    product.content_media.append(_parse_media_item(media))

        return product

    @staticmethod
    def _ensure_list(val) -> list:
        if isinstance(val, list):
            return val
        return [val] if val else []
