from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    cookie: str = ""
    output_dir: str = "./downloads"
    request_delay: float = 2.0
    max_retries: int = 3
    post_dir_format: str = "{yyyy}-{mm}-{dd}_{title}"
    output_info_json: bool = True
    enable_threading: bool = False
    max_workers: int = 4
    skip_existing: bool = True

    @classmethod
    def load(cls, config_path: str | None = None) -> Config:
        """Load config from file. Search order:
        1. Explicit path (from --config flag)
        2. ./config.json (current directory)
        3. ~/.patreon-dl/config.json (user home)
        """
        candidates = []
        if config_path:
            candidates.append(Path(config_path))
        candidates.append(Path("config.json"))
        candidates.append(Path.home() / ".patreon-dl" / "config.json")

        for path in candidates:
            if path.is_file():
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                return cls(
                    cookie=data.get("cookie", ""),
                    output_dir=data.get("output_dir", "./downloads"),
                    request_delay=data.get("request_delay", 2.0),
                    max_retries=data.get("max_retries", 3),
                    post_dir_format=data.get("post_dir_format", "{yyyy}-{mm}-{dd}_{title}"),
                    output_info_json=data.get("output_info_json", True),
                    enable_threading=data.get("enable_threading", False),
                    max_workers=data.get("max_workers", 4),
                    skip_existing=data.get("skip_existing", True),
                )

        return cls()

    def validate(self) -> list[str]:
        """Return list of validation errors."""
        errors = []
        if not self.cookie:
            errors.append(
                "Cookie is not configured. "
                "Set it in config.json or pass --config pointing to your config file."
            )
        return errors
