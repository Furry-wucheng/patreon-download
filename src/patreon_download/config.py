from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .utils import parse_date


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
    # 时间过滤：只下载发布时间在 [date_from, date_to] 内的内容（YYYY-MM-DD，空表示不限）
    date_from: str = ""
    date_to: str = ""
    # 配置实际来源文件（load 时记录，save 时默认写回原文件）
    source_path: Path | None = field(default=None, repr=False, compare=False)

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
                config = cls(
                    cookie=data.get("cookie", ""),
                    output_dir=data.get("output_dir", "./downloads"),
                    request_delay=data.get("request_delay", 2.0),
                    max_retries=data.get("max_retries", 3),
                    post_dir_format=data.get("post_dir_format", "{yyyy}-{mm}-{dd}_{title}"),
                    output_info_json=data.get("output_info_json", True),
                    enable_threading=data.get("enable_threading", False),
                    max_workers=data.get("max_workers", 4),
                    skip_existing=data.get("skip_existing", True),
                    date_from=data.get("date_from", ""),
                    date_to=data.get("date_to", ""),
                )
                config.source_path = path
                return config

        return cls()

    def to_dict(self) -> dict:
        """Serialize config to a plain dict (for writing back to file)."""
        return {
            "cookie": self.cookie,
            "output_dir": self.output_dir,
            "request_delay": self.request_delay,
            "max_retries": self.max_retries,
            "post_dir_format": self.post_dir_format,
            "output_info_json": self.output_info_json,
            "enable_threading": self.enable_threading,
            "max_workers": self.max_workers,
            "skip_existing": self.skip_existing,
            "date_from": self.date_from,
            "date_to": self.date_to,
        }

    def save(self, config_path: str | Path | None = None) -> Path:
        """Write config back to a JSON file.

        Uses the explicit path, the previously loaded ``source_path``, or
        ``./config.json`` as fallback. Returns the path written to.
        """
        path = Path(config_path) if config_path else (self.source_path or Path("config.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=4)
            f.write("\n")
        self.source_path = path
        return path

    def validate(self) -> list[str]:
        """Return list of validation errors."""
        errors = []
        if not self.cookie:
            errors.append(
                "Cookie is not configured. "
                "Set it in config.json or pass --config pointing to your config file."
            )
        for name, value in (("date_from", self.date_from), ("date_to", self.date_to)):
            if value and parse_date(value) is None:
                errors.append(
                    f"{name} 格式无效: {value!r}，应为 YYYY-MM-DD（例如 2025-01-01）"
                )
        if self.date_from and self.date_to:
            from_date = parse_date(self.date_from)
            to_date = parse_date(self.date_to)
            if from_date and to_date and from_date > to_date:
                errors.append("date_from 不能晚于 date_to")
        return errors
