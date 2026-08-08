# Patreon Downloader

一个基于 Python 的 Patreon 内容下载命令行工具，支持下载单个帖子、博主全部帖子和 Shop 商品。

本项目基于https://github.com/patrickkfkan/patreon-dl项目参考重写为Python版本。

## 功能

- **下载单个帖子** — 通过帖子 URL 或 ID 下载图片、视频、音频、附件
- **下载博主全部帖子** — 批量下载某位创作者的所有帖子（自动分页）
- **下载 Shop 商品** — 下载创作者商店中的商品及其媒体文件
- **自定义文件夹命名** — 通过模板变量自定义帖子文件夹名称
- **进度条显示** — 使用 rich 库显示下载进度、速度和剩余时间
- **断点续传** — 已存在的文件自动跳过
- **多线程下载** — 可配置并发线程数加速批量下载
- **文件去重** — 基于 SHA256 哈希的内容级去重，避免重复下载相同文件
- **限速与重试** — 内置请求限速和失败重试机制

## 安装

### 前置要求

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 使用 uv 安装

```bash
git clone https://github.com/your-username/patreon-download.git
cd patreon-download
uv sync
```

### 使用 pip 安装

```bash
pip install -e .
```

## 配置

### 1. 获取 Cookie

1. 登录 [Patreon](https://www.patreon.com/)
2. 打开浏览器开发者工具（F12）
3. 切换到 **Network** 标签
4. 刷新页面，找到任意 `api` 请求
5. 复制请求头中 `Cookie` 字段的完整值

### 2. 创建配置文件

将 `config.json.example` 复制为 `config.json` 并填入你的 Cookie：

```bash
cp config.json.example config.json
```

配置文件内容：

```json
{
    "cookie": "你的Patreon Cookie",
    "output_dir": "./downloads",
    "request_delay": 2.0,
    "max_retries": 3,
    "post_dir_format": "{yyyy}-{mm}-{dd}_{title}",
    "output_info_json": true,
    "enable_threading": false,
    "max_workers": 4,
    "skip_existing": true
}
```

### 配置项说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cookie` | string | `""` | Patreon Cookie（**必填**） |
| `output_dir` | string | `"./downloads"` | 下载输出目录 |
| `request_delay` | float | `2.0` | 每次请求间隔（秒） |
| `max_retries` | int | `3` | 请求失败最大重试次数 |
| `post_dir_format` | string | `"{yyyy}-{mm}-{dd}_{title}"` | 帖子文件夹命名模板 |
| `output_info_json` | bool | `true` | 是否输出 `info.json` 元数据文件 |
| `enable_threading` | bool | `false` | 是否启用多线程下载 |
| `max_workers` | int | `4` | 多线程下载的并发数 |
| `skip_existing` | bool | `true` | 是否跳过已存在的文件（基于文件哈希去重） |

配置文件的查找顺序：

1. `--config` 参数指定的路径
2. 当前目录下的 `config.json`
3. 用户目录下的 `~/.patreon-dl/config.json`

## 使用方法

### 下载单个帖子

```bash
# 通过 URL
patreon-dl post https://www.patreon.com/posts/12345678
patreon-dl post https://www.patreon.com/posts/my-cool-post-12345678

# 通过帖子 ID
patreon-dl post 12345678
```

下载单个帖子时，文件直接保存在输出目录下，**不会**创建作者父文件夹：

```
downloads/
└── 2025-03-20_My Art/
    ├── info.json
    ├── artwork.jpg
    └── source.zip
```

### 下载博主全部帖子

```bash
patreon-dl user https://www.patreon.com/creator/posts
patreon-dl user https://www.patreon.com/c/creator/posts
patreon-dl user https://www.patreon.com/cw/creator/posts
```

批量下载时会自动创建作者文件夹作为上层目录：

```
downloads/
└── Creator Name/
    ├── 2025-03-20_Post One/
    │   ├── info.json
    │   └── image.jpg
    ├── 2025-01-10_Post Two/
    │   └── info.json
    └── ...
```

### 下载 Shop 商品

```bash
patreon-dl shop https://www.patreon.com/creator/shop
```

```
downloads/
└── Creator Name/
    └── shop/
        └── Wallpaper Pack_prod_001/
            ├── info.json
            ├── preview/
            │   └── preview.jpg
            └── content/
                └── wallpapers.zip
```

### 通用参数

```bash
# 指定配置文件
patreon-dl post <url> --config /path/to/config.json

# 指定输出目录
patreon-dl post <url> --output ./my-downloads

# 指定请求间隔
patreon-dl user <url> --delay 5
```

| 参数 | 缩写 | 说明 |
|------|------|------|
| `--config` | `-c` | 配置文件路径 |
| `--output` | `-o` | 输出目录 |
| `--delay` | | 请求间隔（秒） |

## 帖子文件夹命名模板

通过 `post_dir_format` 配置项自定义帖子文件夹名称，支持以下占位符：

| 占位符 | 说明 | 示例 |
|--------|------|------|
| `{yyyy}` | 4 位年份 | `2025` |
| `{mm}` | 2 位月份 | `03` |
| `{dd}` | 2 位日期 | `20` |
| `{date}` | 等同 `{yyyy}-{mm}-{dd}` | `2025-03-20` |
| `{title}` | 帖子标题 | `My Art` |
| `{author}` | 作者名 | `Creator Name` |
| `{id}` | 帖子 ID | `12345678` |

### 示例

```json
// 默认格式
"post_dir_format": "{yyyy}-{mm}-{dd}_{title}"
// => 2025-03-20_My Art

// 包含作者
"post_dir_format": "{author}_{yyyy}{mm}{dd}_{title}"
// => Creator Name_20250320_My Art

// 仅 ID
"post_dir_format": "post_{id}"
// => post_12345678

// 包含全部信息
"post_dir_format": "{yyyy}-{mm}-{dd}_{author}_{title}_{id}"
// => 2025-03-20_Creator Name_My Art_12345678
```

标题中的特殊字符（`<>:"/\|?*`）会被自动替换为下划线。如果日期信息缺失，日期部分会自动省略。

## 多线程下载

通过 `enable_threading` 开启多线程下载，可以显著加速批量下载速度：

```json
{
    "enable_threading": true,
    "max_workers": 4
}
```

开启后，多个文件会同时下载，共享一个进度条显示。`max_workers` 控制并发数，建议根据网络带宽设置为 2-8。

> **注意**：单个帖子下载（`post` 命令）通常文件较少，多线程效果不明显。批量下载（`user` / `shop`）时收益更大。

## 文件去重

默认开启的 `skip_existing` 使用 SHA256 哈希实现内容级去重：

- 下载完成后自动计算文件哈希并记录到 `.hashes.json`
- 再次下载时，即使文件名不同，只要内容相同就会跳过
- 哈希注册表保存在输出目录根目录下（`downloads/.hashes.json`）
- 线程安全，支持多线程下载场景

```json
{
    "skip_existing": true
}
```

如果需要强制重新下载所有文件，将 `skip_existing` 设为 `false` 或删除 `.hashes.json`。

## 开发

### 项目结构

```
patreon-download/
├── pyproject.toml
├── config.json.example
├── src/
│   └── patreon_download/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py          # CLI 入口
│       ├── config.py       # 配置加载
│       ├── api.py          # Patreon API 客户端
│       ├── models.py       # 数据模型
│       ├── downloader.py   # 文件下载
│       └── utils.py        # 工具函数
└── tests/
    ├── conftest.py         # 测试 fixtures
    ├── test_api.py
    ├── test_cli.py
    ├── test_config.py
    ├── test_downloader.py
    └── test_utils.py
```

### 运行测试

```bash
# 运行全部测试
uv run pytest tests/ -v

# 运行指定模块
uv run pytest tests/test_utils.py -v

# 带覆盖率
uv run pytest tests/ --cov=patreon_download
```

### 开发模式运行

```bash
# 通过 uv run
uv run patreon-dl --help

# 通过 python -m
uv run python -m patreon_download --help
```

## 注意事项

- **Cookie 有效期**：Cookie 会过期，遇到认证错误时需要重新获取
- **请求频率**：Patreon 有请求频率限制，建议保持 `request_delay` 在 2 秒以上
- **DRM 视频**：部分视频有 DRM 保护，下载后可能无法正常播放
- **付费内容**：只能下载你的账号有权访问的内容

## License

MIT
