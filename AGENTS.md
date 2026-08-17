# AGENTS.md

Patreon 内容下载 CLI（Python 3.13+，uv 管理依赖）。本文件是给 OpenCode 会话的指引；另有 CLAUDE.md 内容基本与此一致，改动时保持同步。

## 命令

```bash
uv sync                              # 安装依赖（含 dev 组：pytest、pytest-cov）
uv run patreon-dl post <url|id>      # 单帖（post 直接存输出目录，不建作者目录）
uv run patreon-dl user <url>         # 全部帖子（user/shop 会建"作者名/"上层目录）
uv run patreon-dl shop <url>         # shop 商品（建"作者名/shop/商品名_id/"）
uv run python -m patreon_download --help
uv run pytest tests/ -v              # 全部测试（pyproject 已设 addopts: -v --tb=short）
uv run pytest tests/test_utils.py -v # 单文件
uv run pytest tests/ --cov=patreon_download
```

无 lint/typecheck 配置，pytest 是唯一验证手段。不要编造 ruff/mypy 命令。

## 配置

- `config.json` 被 `.gitignore` 忽略（含 Cookie 密钥）；模板见 `config.json.example`。别提交真实 Cookie。
- 查找顺序：`--config` 指定 > `./config.json` > `~/.patreon-dl/config.json`。
- `cookie` 必填，否则 `validate()` 报错退出（cli.py:80-84）。
- CLI 常用参数：`-c/--config`、`-o/--output`、`--delay`（CLI 覆盖文件配置）。

## 架构

- 数据流：`cli.py` 解析参数 → `Config.load()` → `PatreonClient`（api.py）拉 JSON:API → `Post`/`Product` 模型 → `downloader.py` 落盘。
- `api.py` 用 `_safe_get()` 遍历嵌套 dict（**None 视为缺失**）；`_parse_post`/`_parse_product` 通过 `included` 数组按 id+type 查找关联资源。
- `get_initial_data()` 抓 HTML 提取 campaign_id，三种回退方式（`window.patreon` → `__NEXT_DATA__` → 流式 URL 正则）。**Patreon 页面结构常变**，改这里必须同步更新 test_api.py 的解析测试。
- 去重：`HashRegistry`（`.hashes.json` 存于输出目录根），SHA256 内容级去重，多线程下有锁保护；`skip_existing` 关闭时不创建 registry。`.hashes.json` 只在 CLI 命令结束时 `save()`，进程中断会丢失增量。
- 分页：posts 用 `links.next` + `page[cursor]`；products 用 offset 步长 24。
- 下载：`_download_file` 流式下载，失败重试、部分文件会被删除；多线程共享一个 rich Progress 条（`task_ids` 按 URL 索引——URL 相同会冲突，改这里注意）。

## 测试注意

- 全部测试**离线**：API 响应用 `conftest.py` 的 fixture（`sample_post_response` 等），网络用 `monkeypatch` 伪造（如 `patreon_download.downloader.requests.get`）。
- 新增解析逻辑时，先在 `tests/conftest.py` 扩 mock 数据，再写断言。
- `extract_user_info`/`extract_post_id` 是正则解析 URL，用例集中在 test_utils.py。

## 项目约定

- README均为中文；文档改动保持中文。
- 文件命名：`utils.sanitize_filename`（替换 `<>:"/\|?*`、截断 200 字符）；帖子目录名走 `post_dir_format` 模板（`{yyyy}-{mm}-{dd}_{title}` 等）。
- 兼容性：依赖极简（requests + rich），新增依赖需谨慎。
- Git commit message 标题统一使用 `type(scope): 中文描述` 格式：
  - `type` 和 `scope` 必须使用英文；`type` 使用 `feat`、`fix`、`refactor`、`docs`、`test`、`chore` 等规范类型，`scope` 使用英文模块名或功能名。
  - `desc` 必须使用中文，简洁说明本次修改的核心内容。
  - 改动较多或需要补充上下文时，在标题后空一行，并在正文使用 `- 中文分点说明` 列出主要改动；简单改动无需强行增加分点。
  - 必须在 commit 前把完整 commit message（包括正文分点）交给用户审核，审核通过后才能执行 commit 和 push。
