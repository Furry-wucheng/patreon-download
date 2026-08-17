"""Tests for cli.py — argument parsing and command dispatch."""

import pytest

from patreon_download.cli import build_parser


class TestArgParsing:
    """Test CLI argument parsing."""

    def test_post_command(self):
        parser = build_parser()
        args = parser.parse_args(["post", "https://www.patreon.com/posts/12345"])
        assert args.command == "post"
        assert args.url == "https://www.patreon.com/posts/12345"

    def test_user_command(self):
        parser = build_parser()
        args = parser.parse_args(["user", "https://www.patreon.com/creator/posts"])
        assert args.command == "user"
        assert args.url == "https://www.patreon.com/creator/posts"

    def test_shop_command(self):
        parser = build_parser()
        args = parser.parse_args(["shop", "https://www.patreon.com/creator/shop"])
        assert args.command == "shop"
        assert args.url == "https://www.patreon.com/creator/shop"

    def test_optional_output(self):
        parser = build_parser()
        args = parser.parse_args(["post", "https://x.com/posts/1", "--output", "/tmp/out"])
        assert args.output == "/tmp/out"

    def test_optional_config(self):
        parser = build_parser()
        args = parser.parse_args(["post", "https://x.com/posts/1", "-c", "my.json"])
        assert args.config == "my.json"

    def test_optional_delay(self):
        parser = build_parser()
        args = parser.parse_args(["post", "https://x.com/posts/1", "--delay", "5.0"])
        assert args.delay == 5.0

    def test_no_command_errors(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_unknown_command_errors(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["download", "https://x.com/posts/1"])

    def test_gui_command(self):
        parser = build_parser()
        args = parser.parse_args(["gui"])
        assert args.command == "gui"

    def test_gui_command_with_config(self):
        parser = build_parser()
        args = parser.parse_args(["gui", "-c", "my.json"])
        assert args.command == "gui"
        assert args.config == "my.json"

    def test_user_date_filter_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "user", "https://www.patreon.com/creator/posts",
            "--date-from", "2024-01-01", "--date-to", "2024-06-30",
        ])
        assert args.date_from == "2024-01-01"
        assert args.date_to == "2024-06-30"

    def test_shop_date_filter_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "shop", "https://www.patreon.com/creator/shop",
            "--date-from", "2025-01-01",
        ])
        assert args.date_from == "2025-01-01"
        assert args.date_to is None

    def test_post_has_no_date_filter_args(self):
        """单帖下载不提供时间过滤参数。"""
        parser = build_parser()
        args = parser.parse_args(["post", "https://www.patreon.com/posts/12345"])
        assert not hasattr(args, "date_from")
