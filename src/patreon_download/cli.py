from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .api import PatreonClient
from .config import Config
from .downloader import HashRegistry, download_post, download_product, console
from .utils import extract_post_id, extract_user_info

DESCRIPTION = """\
Patreon Downloader — download posts, user content, and shop items.

Examples:
  patreon-dl post https://www.patreon.com/posts/12345678
  patreon-dl user https://www.patreon.com/creator/posts
  patreon-dl shop https://www.patreon.com/creator/shop
"""


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", "-c", metavar="PATH",
        help="Path to config.json (default: ./config.json or ~/.patreon-dl/config.json)",
    )
    parser.add_argument(
        "--output", "-o", metavar="DIR",
        help="Output directory (default: ./downloads)",
    )
    parser.add_argument(
        "--delay", type=float, metavar="SEC",
        help="Delay between requests in seconds (default: 2.0)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="patreon-dl",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _add_common_args(parser)

    sub = parser.add_subparsers(dest="command", required=True)

    # ── post ──
    p_post = sub.add_parser("post", help="Download a single post by URL or ID")
    p_post.add_argument("url", help="Post URL or numeric ID")
    _add_common_args(p_post)

    # ── user ──
    p_user = sub.add_parser("user", help="Download all posts from a creator")
    p_user.add_argument("url", help="Creator URL (e.g. https://www.patreon.com/creator/posts)")
    _add_common_args(p_user)

    # ── shop ──
    p_shop = sub.add_parser("shop", help="Download shop items from a creator")
    p_shop.add_argument("url", help="Shop URL (e.g. https://www.patreon.com/creator/shop)")
    _add_common_args(p_shop)

    return parser


def _load_config(args) -> Config:
    config = Config.load(getattr(args, "config", None))
    if getattr(args, "output", None):
        config.output_dir = args.output
    if getattr(args, "delay", None) is not None:
        config.request_delay = args.delay
    return config


def _cmd_post(args) -> int:
    config = _load_config(args)
    errors = config.validate()
    if errors:
        for e in errors:
            console.print(f"[red]Error:[/red] {e}")
        return 1

    # Extract post ID
    url = args.url.strip()
    post_id = extract_post_id(url) if "/" in url else url
    if not post_id or not post_id.isdigit():
        console.print(f"[red]Error:[/red] Cannot extract post ID from: {url}")
        return 1

    client = PatreonClient(config)
    console.print(f"Fetching post [cyan]{post_id}[/cyan] ...")
    post = client.fetch_post(post_id)

    console.print(f"Title: [bold]{post.title or '(untitled)'}[/bold]")
    if post.author_name:
        console.print(f"Author: [bold]{post.author_name}[/bold]")
    if not post.is_viewable:
        console.print("[yellow]Warning:[/yellow] This post may not be fully accessible.")

    output_dir = Path(config.output_dir)
    registry = HashRegistry(output_dir) if config.skip_existing else None
    count = download_post(post, output_dir, config, use_author_dir=False, registry=registry)
    if registry:
        registry.save()
    console.print(f"[green]Done![/green] Downloaded {count} file(s)")
    return 0


def _cmd_user(args) -> int:
    config = _load_config(args)
    errors = config.validate()
    if errors:
        for e in errors:
            console.print(f"[red]Error:[/red] {e}")
        return 1

    user_info = extract_user_info(args.url)
    if not user_info:
        console.print(f"[red]Error:[/red] Cannot extract creator info from: {args.url}")
        return 1

    client = PatreonClient(config)
    console.print(f"Resolving creator [cyan]{user_info['value']}[/cyan] ...")
    initial = client.get_initial_data(user_info["value"])

    campaign_id = initial.get("campaign_id")
    if not campaign_id:
        status = initial.get("http_status", "?")
        console.print(f"[red]Error:[/red] Could not find campaign ID (HTTP {status}).")
        console.print("  Possible causes:")
        console.print("  - Cookie is invalid or expired (update config.json)")
        console.print("  - Creator URL is incorrect")
        console.print("  - Patreon page structure changed")
        console.print(f"  Tried URL: [dim]https://www.patreon.com/{user_info['value']}/posts[/dim]")
        return 1

    current_user_id = initial.get("current_user_id")
    author_name = initial.get("author_name", user_info["value"])
    console.print(f"Campaign ID: [cyan]{campaign_id}[/cyan]")
    console.print(f"Author: [bold]{author_name}[/bold]")

    def on_page(loaded, total):
        console.print(f"  Fetched {loaded}/{total} posts ...")

    posts = client.fetch_all_posts(campaign_id, current_user_id, on_page=on_page)
    console.print(f"Found [bold]{len(posts)}[/bold] posts. Starting download ...")

    output_dir = Path(config.output_dir)
    registry = HashRegistry(output_dir) if config.skip_existing else None
    total_files = 0
    for i, post in enumerate(posts, 1):
        console.print(f"[{i}/{len(posts)}] {post.title or post.id}")
        total_files += download_post(post, output_dir, config, author_name=author_name, registry=registry)

    if registry:
        registry.save()
    console.print(f"[green]Done![/green] Downloaded {total_files} file(s) from {len(posts)} posts.")
    return 0


def _cmd_shop(args) -> int:
    config = _load_config(args)
    errors = config.validate()
    if errors:
        for e in errors:
            console.print(f"[red]Error:[/red] {e}")
        return 1

    user_info = extract_user_info(args.url)
    if not user_info:
        console.print(f"[red]Error:[/red] Cannot extract creator info from: {args.url}")
        return 1

    client = PatreonClient(config)
    console.print(f"Resolving creator [cyan]{user_info['value']}[/cyan] ...")
    initial = client.get_initial_data(user_info["value"])

    campaign_id = initial.get("campaign_id")
    if not campaign_id:
        status = initial.get("http_status", "?")
        console.print(f"[red]Error:[/red] Could not find campaign ID (HTTP {status}).")
        console.print("  Possible causes:")
        console.print("  - Cookie is invalid or expired (update config.json)")
        console.print("  - Creator URL is incorrect")
        console.print("  - Patreon page structure changed")
        console.print(f"  Tried URL: [dim]https://www.patreon.com/{user_info['value']}/posts[/dim]")
        return 1

    author_name = initial.get("author_name", user_info["value"])
    console.print(f"Author: [bold]{author_name}[/bold]")

    def on_page(loaded):
        console.print(f"  Fetched {loaded} products ...")

    products = client.fetch_all_products(campaign_id, on_page=on_page)
    console.print(f"Found [bold]{len(products)}[/bold] products. Starting download ...")

    output_dir = Path(config.output_dir)
    registry = HashRegistry(output_dir) if config.skip_existing else None
    total_files = 0
    for i, product in enumerate(products, 1):
        console.print(f"[{i}/{len(products)}] {product.name or product.id}")
        total_files += download_product(product, output_dir, config, author_name=author_name, registry=registry)

    if registry:
        registry.save()
    console.print(f"[green]Done![/green] Downloaded {total_files} file(s) from {len(products)} products.")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "post": _cmd_post,
        "user": _cmd_user,
        "shop": _cmd_shop,
    }
    try:
        sys.exit(dispatch[args.command](args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
