"""Patreon Downloader 图形界面（tkinter）。

功能：
- 编辑配置（Cookie、输出目录、限速、线程、时间过滤等）
- 配置与 config.json 双向同步：启动时从配置文件读取，修改后写回原文件
- 按时间范围过滤下载内容（date_from / date_to）
- 下载单个帖子 / 全部帖子 / Shop 商品，日志实时显示，支持停止

启动方式：
    python -m patreon_download.gui
    patreon-dl gui [--config PATH]
"""

from __future__ import annotations

import calendar
import queue
import threading
import tkinter as tk
from datetime import date as date_cls
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from rich.console import Console

from . import downloader
from .api import PatreonClient
from .config import Config
from .downloader import CancelledError, HashRegistry, download_post, download_product
from .utils import extract_post_id, extract_user_info, parse_date

KINDS = {
    "post": "单个帖子",
    "user": "创作者内容",
    "shop": "Shop 商品",
}
KIND_LABELS = {label: key for key, label in KINDS.items()}

KIND_COPY = {
    "post": ("帖子 URL 或数字 ID", "只归档这一篇内容，不创建作者上层目录。"),
    "user": ("创作者主页或 Posts 链接", "归档创作者的全部可访问帖子。"),
    "shop": ("创作者 Shop 链接", "归档可访问商品并保留目录结构。"),
}

COLORS = {
    "bg": "#0B1017",
    "sidebar": "#0E141D",
    "surface": "#121A25",
    "surface_alt": "#17212E",
    "input": "#0D141E",
    "border": "#263241",
    "border_focus": "#FF6B55",
    "text": "#F2F4F7",
    "muted": "#8996A8",
    "faint": "#586577",
    "accent": "#FF5E48",
    "accent_hover": "#FF735F",
    "accent_soft": "#35201F",
    "success": "#6BD6A6",
    "warning": "#F3BE66",
    "danger": "#FF7C7C",
}

UI_FONT = "Microsoft YaHei UI"
DISPLAY_FONT = "Bahnschrift SemiBold"
MONO_FONT = "Cascadia Mono"


class _DatePicker(tk.Toplevel):
    """纯 tkinter 实现的日历选择弹窗（无第三方依赖）。

    点击日期后通过 ``on_select`` 回调返回 ``YYYY-MM-DD`` 字符串。
    """

    WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")
    MONTHS = ("1月", "2月", "3月", "4月", "5月", "6月",
              "7月", "8月", "9月", "10月", "11月", "12月")

    def __init__(
        self, master: tk.Misc, initial: str = "",
        on_select: object | None = None,
    ) -> None:
        super().__init__(master)
        self.title("选择日期")
        self.resizable(False, False)
        self.transient(master)
        self.configure(bg=COLORS["surface"])
        self.on_select = on_select

        today = date_cls.today()
        start = parse_date(initial) or today
        self._year = start.year
        self._month = start.month
        self._today = today
        self._selected: int | None = None

        self._build()
        self._redraw()

        # 居中显示在父窗口附近
        self.update_idletasks()
        x = master.winfo_rootx() + max((master.winfo_width() - self.winfo_width()) // 2, 0)
        y = master.winfo_rooty() + max((master.winfo_height() - self.winfo_height()) // 2, 0)
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    # ── 构建 ────────────────────────────────────────────────────

    def _build(self) -> None:
        header = ttk.Frame(self, padding=(14, 14, 14, 8), style="Card.TFrame")
        header.pack(fill="x")
        ttk.Button(
            header, text="‹‹", width=3, command=self._prev_year, style="Icon.TButton"
        ).pack(side="left")
        ttk.Button(
            header, text="‹", width=3, command=self._prev_month, style="Icon.TButton"
        ).pack(side="left", padx=(4, 10))
        self._title_var = tk.StringVar()
        ttk.Label(
            header, textvariable=self._title_var, style="CalendarTitle.TLabel"
        ).pack(side="left", expand=True)
        ttk.Button(
            header, text="›", width=3, command=self._next_month, style="Icon.TButton"
        ).pack(side="right", padx=(10, 4))
        ttk.Button(
            header, text="››", width=3, command=self._next_year, style="Icon.TButton"
        ).pack(side="right")

        week = ttk.Frame(self, padding=(14, 4, 14, 4), style="Card.TFrame")
        week.pack(fill="x")
        for i, weekday in enumerate(self.WEEKDAYS):
            ttk.Label(
                week, text=weekday, width=4, anchor="center", style="CalendarWeek.TLabel"
            ).grid(row=0, column=i, padx=2)

        self._days_frame = ttk.Frame(
            self, padding=(14, 2, 14, 10), style="Card.TFrame"
        )
        self._days_frame.pack(fill="x")

        footer = ttk.Frame(self, padding=(14, 10, 14, 14), style="Card.TFrame")
        footer.pack(fill="x")
        ttk.Button(
            footer, text="今天", command=self._select_today, style="Secondary.TButton"
        ).pack(side="left")
        ttk.Button(
            footer, text="清除", command=self._clear, style="Ghost.TButton"
        ).pack(side="left", padx=6)
        ttk.Button(
            footer, text="取消", command=self.destroy, style="Ghost.TButton"
        ).pack(side="right")

    def _redraw(self) -> None:
        self._title_var.set(f"{self._year} 年 {self.MONTHS[self._month - 1]}")
        for child in self._days_frame.winfo_children():
            child.destroy()

        first_weekday, days_in_month = calendar.monthrange(self._year, self._month)
        for day in range(1, days_in_month + 1):
            col = (first_weekday + day - 1) % 7
            row = (first_weekday + day - 1) // 7
            is_today = (self._year, self._month, day) == (
                self._today.year, self._today.month, self._today.day
            )
            bg = COLORS["accent"] if is_today else COLORS["surface_alt"]
            fg = COLORS["text"]
            btn = tk.Button(
                self._days_frame, text=str(day), width=4, height=1,
                bg=bg, fg=fg, activebackground=COLORS["accent_hover"],
                activeforeground=COLORS["text"], relief="flat", bd=0,
                font=(UI_FONT, 9), cursor="hand2", highlightthickness=0,
                command=lambda d=day: self._select(d),
            )
            btn.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")

    # ── 翻页 / 选择 ─────────────────────────────────────────────

    def _prev_month(self) -> None:
        self._year, self._month = (
            (self._year - 1, 12) if self._month == 1 else (self._year, self._month - 1)
        )
        self._redraw()

    def _next_month(self) -> None:
        self._year, self._month = (
            (self._year + 1, 1) if self._month == 12 else (self._year, self._month + 1)
        )
        self._redraw()

    def _prev_year(self) -> None:
        self._year -= 1
        self._redraw()

    def _next_year(self) -> None:
        self._year += 1
        self._redraw()

    def _select(self, day: int) -> None:
        value = f"{self._year:04d}-{self._month:02d}-{day:02d}"
        if self.on_select:
            self.on_select(value)
        self.destroy()

    def _select_today(self) -> None:
        self._year, self._month = self._today.year, self._today.month
        self._redraw()
        self._select(self._today.day)

    def _clear(self) -> None:
        if self.on_select:
            self.on_select("")
        self.destroy()


class _LogWriter:
    """rich Console 的自定义输出目标：把每一行文本送入线程安全队列。"""

    def __init__(self, log_queue: queue.Queue) -> None:
        self._queue = log_queue
        self._buffer = ""

    def write(self, s: str) -> None:
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip()
            if line:
                self._queue.put(("info", line))

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class PatreonGUI:
    def __init__(self, root: tk.Tk, config_path: str | None = None) -> None:
        self.root = root
        self.root.title("Patreon Archive — 下载工作台")
        window_width, window_height = 1120, 700
        window_x = max((self.root.winfo_screenwidth() - window_width) // 2, 0)
        window_y = max((self.root.winfo_screenheight() - window_height) // 2, 0)
        self.root.geometry(
            f"{window_width}x{window_height}+{window_x}+{window_y}"
        )
        self.root.minsize(940, 620)
        self.root.configure(bg=COLORS["bg"])

        self._log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._cancel_event = threading.Event()
        self._running = False
        self._worker: threading.Thread | None = None

        # rich 日志输出：GUI 期间把 downloader 的全局 console 换成这个
        self._gui_console = Console(
            file=_LogWriter(self._log_queue),
            color_system=None,
            soft_wrap=True,
        )

        self.config = Config.load(config_path)

        # ── 控件变量 ──────────────────────────────────────────────
        self.path_var = tk.StringVar(
            value=str(self.config.source_path) if self.config.source_path else "config.json"
        )
        self.cookie_var = tk.StringVar(value=self.config.cookie)
        self.output_dir_var = tk.StringVar(value=self.config.output_dir)
        self.delay_var = tk.StringVar(value=str(self.config.request_delay))
        self.retries_var = tk.StringVar(value=str(self.config.max_retries))
        self.dir_format_var = tk.StringVar(value=self.config.post_dir_format)
        self.info_json_var = tk.BooleanVar(value=self.config.output_info_json)
        self.threading_var = tk.BooleanVar(value=self.config.enable_threading)
        self.workers_var = tk.StringVar(value=str(self.config.max_workers))
        self.skip_existing_var = tk.BooleanVar(value=self.config.skip_existing)
        self.date_from_var = tk.StringVar(value=self.config.date_from)
        self.date_to_var = tk.StringVar(value=self.config.date_to)
        self.cookie_visible_var = tk.BooleanVar(value=False)

        self.kind_var = tk.StringVar(value=KINDS["user"])
        self.url_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就绪")
        self.status_detail_var = tk.StringVar(value="等待新的下载任务")
        self.page_title_var = tk.StringVar(value="下载任务")
        self.page_subtitle_var = tk.StringVar(value="创建并管理你的 Patreon 本地归档")
        self.kind_placeholder_var = tk.StringVar()
        self.kind_description_var = tk.StringVar()

        self._configure_styles()
        self._build_ui()
        self._select_kind("user")
        self._show_page("task")
        self.root.bind("<Control-Return>", lambda _event: self._on_start())
        self.root.bind("<Control-s>", lambda _event: self._save_config())
        self.root.bind("<Escape>", lambda _event: self._on_stop())
        self.root.after(100, self._poll_log)

    # ── UI 构建 ───────────────────────────────────────────────────

    def _configure_styles(self) -> None:
        """建立统一的深色视觉系统。"""
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("Main.TFrame", background=COLORS["bg"])
        style.configure("Sidebar.TFrame", background=COLORS["sidebar"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure("Subtle.TFrame", background=COLORS["surface_alt"])
        style.configure("Field.TFrame", background=COLORS["surface_alt"])

        style.configure(
            "TLabel", background=COLORS["bg"], foreground=COLORS["text"],
            font=(UI_FONT, 10),
        )
        style.configure(
            "Sidebar.TLabel", background=COLORS["sidebar"], foreground=COLORS["text"],
            font=(UI_FONT, 10),
        )
        style.configure(
            "SidebarMuted.TLabel", background=COLORS["sidebar"],
            foreground=COLORS["muted"], font=(UI_FONT, 9),
        )
        style.configure(
            "Card.TLabel", background=COLORS["surface"], foreground=COLORS["text"],
            font=(UI_FONT, 10),
        )
        style.configure(
            "Muted.TLabel", background=COLORS["surface"], foreground=COLORS["muted"],
            font=(UI_FONT, 9),
        )
        style.configure(
            "Subtle.TLabel", background=COLORS["surface_alt"],
            foreground=COLORS["text"], font=(UI_FONT, 10),
        )
        style.configure(
            "SubtleMuted.TLabel", background=COLORS["surface_alt"],
            foreground=COLORS["muted"], font=(UI_FONT, 9),
        )
        style.configure(
            "PageTitle.TLabel", background=COLORS["bg"], foreground=COLORS["text"],
            font=(DISPLAY_FONT, 24),
        )
        style.configure(
            "PageSubtitle.TLabel", background=COLORS["bg"], foreground=COLORS["muted"],
            font=(UI_FONT, 10),
        )
        style.configure(
            "CardTitle.TLabel", background=COLORS["surface"], foreground=COLORS["text"],
            font=(UI_FONT, 15, "bold"),
        )
        style.configure(
            "Eyebrow.TLabel", background=COLORS["surface"], foreground=COLORS["accent"],
            font=(DISPLAY_FONT, 9),
        )
        style.configure(
            "FieldLabel.TLabel", background=COLORS["surface"], foreground=COLORS["text"],
            font=(UI_FONT, 9, "bold"),
        )
        style.configure(
            "Section.TLabel", background=COLORS["surface"], foreground=COLORS["text"],
            font=(UI_FONT, 11, "bold"),
        )
        style.configure(
            "Status.TLabel", background=COLORS["sidebar"], foreground=COLORS["text"],
            font=(UI_FONT, 9, "bold"),
        )

        entry_options = {
            "fieldbackground": COLORS["input"], "foreground": COLORS["text"],
            "insertcolor": COLORS["text"], "bordercolor": COLORS["border"],
            "lightcolor": COLORS["border"], "darkcolor": COLORS["border"],
            "padding": (11, 9), "font": (UI_FONT, 10),
        }
        style.configure("TEntry", **entry_options)
        style.configure("Compact.TEntry", padding=(8, 6), font=(UI_FONT, 9))
        style.map(
            "TEntry",
            bordercolor=[("focus", COLORS["border_focus"])],
            lightcolor=[("focus", COLORS["border_focus"])],
            foreground=[("disabled", COLORS["faint"]), ("readonly", COLORS["muted"])],
        )

        style.configure(
            "TButton", background=COLORS["surface_alt"], foreground=COLORS["text"],
            bordercolor=COLORS["border"], lightcolor=COLORS["border"],
            darkcolor=COLORS["border"], font=(UI_FONT, 9), padding=(12, 8),
        )
        style.map(
            "TButton",
            background=[("active", "#202C3B"), ("disabled", COLORS["surface"])],
            foreground=[("disabled", COLORS["faint"])],
        )
        style.configure(
            "Accent.TButton", background=COLORS["accent"], foreground="#FFFFFF",
            bordercolor=COLORS["accent"], lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent"], font=(UI_FONT, 10, "bold"), padding=(18, 11),
        )
        style.map(
            "Accent.TButton",
            background=[("active", COLORS["accent_hover"]), ("disabled", "#55302D")],
            foreground=[("disabled", "#A97872")],
        )
        style.configure("Secondary.TButton", padding=(13, 8))
        style.configure("Compact.TButton", padding=(8, 5), font=(UI_FONT, 9))
        style.configure(
            "Ghost.TButton", background=COLORS["surface"], bordercolor=COLORS["surface"],
            lightcolor=COLORS["surface"], darkcolor=COLORS["surface"],
            foreground=COLORS["muted"], padding=(9, 6),
        )
        style.map(
            "Ghost.TButton", background=[("active", COLORS["surface_alt"])],
            foreground=[("active", COLORS["text"])],
        )
        style.configure(
            "Danger.TButton", background=COLORS["surface"], foreground=COLORS["danger"],
            bordercolor="#57343A", lightcolor="#57343A", darkcolor="#57343A",
            padding=(14, 10), font=(UI_FONT, 9, "bold"),
        )
        style.map("Danger.TButton", background=[("active", "#2C1B22")])
        style.configure(
            "Icon.TButton", background=COLORS["surface_alt"], bordercolor=COLORS["surface_alt"],
            lightcolor=COLORS["surface_alt"], darkcolor=COLORS["surface_alt"], padding=(5, 4),
            font=(UI_FONT, 12),
        )

        style.configure(
            "TCheckbutton", background=COLORS["surface_alt"], foreground=COLORS["text"],
            font=(UI_FONT, 9), padding=(0, 3),
        )
        style.map(
            "TCheckbutton", background=[("active", COLORS["surface_alt"])],
            indicatorcolor=[("selected", COLORS["accent"]), ("!selected", COLORS["input"])],
        )
        style.configure(
            "Card.TCheckbutton", background=COLORS["surface"], foreground=COLORS["text"],
            font=(UI_FONT, 9), padding=(0, 3),
        )
        style.map(
            "Card.TCheckbutton", background=[("active", COLORS["surface"])],
            indicatorcolor=[("selected", COLORS["accent"]), ("!selected", COLORS["input"])],
        )
        style.configure(
            "Accent.Horizontal.TProgressbar", background=COLORS["accent"],
            troughcolor=COLORS["input"], bordercolor=COLORS["input"], thickness=3,
        )
        style.configure(
            "Vertical.TScrollbar", background=COLORS["surface_alt"],
            troughcolor=COLORS["surface"], bordercolor=COLORS["surface"],
            arrowcolor=COLORS["muted"],
        )
        style.configure(
            "CalendarTitle.TLabel", background=COLORS["surface"],
            foreground=COLORS["text"], font=(UI_FONT, 11, "bold"),
        )
        style.configure(
            "CalendarWeek.TLabel", background=COLORS["surface"],
            foreground=COLORS["muted"], font=(UI_FONT, 9),
        )

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._build_sidebar()

        content = ttk.Frame(self.root, padding=(28, 22, 28, 24), style="Main.TFrame")
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)

        header = ttk.Frame(content, style="Main.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, textvariable=self.page_title_var, style="PageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header, textvariable=self.page_subtitle_var, style="PageSubtitle.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        config_bar = ttk.Frame(content, padding=(14, 10), style="Card.TFrame")
        config_bar.grid(row=1, column=0, sticky="ew", pady=(18, 16))
        config_bar.columnconfigure(1, weight=1)
        ttk.Label(config_bar, text="CONFIG", style="Eyebrow.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Entry(config_bar, textvariable=self.path_var).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(
            config_bar, text="选择", command=self._browse_config, style="Ghost.TButton"
        ).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(
            config_bar, text="重载", command=self._reload_config, style="Ghost.TButton"
        ).grid(row=0, column=3)
        ttk.Button(
            config_bar, text="保存", command=self._save_config, style="Secondary.TButton"
        ).grid(row=0, column=4, padx=(6, 0))

        body = ttk.Frame(content, style="Main.TFrame")
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3, uniform="body")
        body.columnconfigure(1, weight=2, uniform="body")
        body.rowconfigure(0, weight=1)

        self._page_host = ttk.Frame(body, style="Main.TFrame")
        self._page_host.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self._page_host.columnconfigure(0, weight=1)
        self._page_host.rowconfigure(0, weight=1)
        self._build_task_page(self._page_host)
        self._build_settings_page(self._page_host)
        self._build_activity_panel(body)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_sidebar(self) -> None:
        sidebar = ttk.Frame(self.root, width=214, padding=(20, 22), style="Sidebar.TFrame")
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(5, weight=1)

        brand = ttk.Frame(sidebar, style="Sidebar.TFrame")
        brand.grid(row=0, column=0, sticky="ew")
        mark = tk.Canvas(
            brand, width=42, height=42, bg=COLORS["sidebar"],
            highlightthickness=0, bd=0,
        )
        mark.pack(side="left")
        mark.create_rectangle(7, 7, 14, 35, fill=COLORS["accent"], outline="")
        mark.create_oval(18, 7, 35, 24, fill=COLORS["accent"], outline="")
        brand_text = ttk.Frame(brand, style="Sidebar.TFrame")
        brand_text.pack(side="left", padx=(10, 0))
        ttk.Label(
            brand_text, text="PATRON", style="Sidebar.TLabel",
            font=(DISPLAY_FONT, 14),
        ).pack(anchor="w")
        ttk.Label(
            brand_text, text="ARCHIVE", style="SidebarMuted.TLabel",
            font=(DISPLAY_FONT, 8),
        ).pack(anchor="w")

        ttk.Label(sidebar, text="工作区", style="SidebarMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(38, 10)
        )
        self.nav_task_btn = self._nav_button(sidebar, "01  下载任务", "task")
        self.nav_task_btn.grid(row=2, column=0, sticky="ew", pady=2)
        self.nav_settings_btn = self._nav_button(sidebar, "02  偏好设置", "settings")
        self.nav_settings_btn.grid(row=3, column=0, sticky="ew", pady=2)

        shortcuts = ttk.Frame(sidebar, padding=(0, 18), style="Sidebar.TFrame")
        shortcuts.grid(row=4, column=0, sticky="ew", pady=(28, 0))
        ttk.Label(shortcuts, text="快捷键", style="SidebarMuted.TLabel").pack(anchor="w")
        ttk.Label(
            shortcuts, text="Ctrl + Enter   开始\nCtrl + S        保存\nEsc               停止",
            style="SidebarMuted.TLabel", justify="left",
        ).pack(anchor="w", pady=(8, 0))

        status_box = ttk.Frame(sidebar, padding=(12, 12), style="Subtle.TFrame")
        status_box.grid(row=6, column=0, sticky="sew")
        status_top = ttk.Frame(status_box, style="Subtle.TFrame")
        status_top.pack(fill="x")
        self.status_dot = tk.Canvas(
            status_top, width=12, height=12, bg=COLORS["surface_alt"],
            highlightthickness=0,
        )
        self.status_dot.pack(side="left")
        self._status_dot_id = self.status_dot.create_oval(
            2, 2, 10, 10, fill=COLORS["success"], outline=""
        )
        ttk.Label(
            status_top, textvariable=self.status_var, style="Subtle.TLabel",
            font=(UI_FONT, 9, "bold"),
        ).pack(side="left", padx=(7, 0))
        ttk.Label(
            status_box, textvariable=self.status_detail_var,
            style="SubtleMuted.TLabel", wraplength=150, justify="left",
        ).pack(anchor="w", pady=(6, 0))

    def _nav_button(self, parent: tk.Widget, text: str, page: str) -> tk.Button:
        return tk.Button(
            parent, text=text, command=lambda: self._show_page(page), anchor="w",
            bg=COLORS["sidebar"], fg=COLORS["muted"],
            activebackground=COLORS["surface_alt"], activeforeground=COLORS["text"],
            relief="flat", bd=0, highlightthickness=0, padx=12, pady=10,
            font=(UI_FONT, 10), cursor="hand2",
        )

    def _show_page(self, page: str) -> None:
        is_task = page == "task"
        if is_task:
            self._settings_page.grid_remove()
            self._task_page.grid()
            self.page_title_var.set("下载任务")
            self.page_subtitle_var.set("创建并管理你的 Patreon 本地归档")
        else:
            self._task_page.grid_remove()
            self._settings_page.grid()
            self.page_title_var.set("偏好设置")
            self.page_subtitle_var.set("控制下载行为、目录结构与访问凭据")
        active, inactive = COLORS["surface_alt"], COLORS["sidebar"]
        self.nav_task_btn.configure(
            bg=active if is_task else inactive,
            fg=COLORS["text"] if is_task else COLORS["muted"],
        )
        self.nav_settings_btn.configure(
            bg=inactive if is_task else active,
            fg=COLORS["muted"] if is_task else COLORS["text"],
        )

    def _build_task_page(self, parent: ttk.Frame) -> None:
        self._task_page = ttk.Frame(parent, padding=(20, 16), style="Card.TFrame")
        self._task_page.grid(row=0, column=0, sticky="nsew")
        self._task_page.columnconfigure(0, weight=1)
        self._task_page.rowconfigure(8, weight=1)

        ttk.Label(self._task_page, text="NEW ARCHIVE", style="Eyebrow.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self._task_page, text="选择归档范围", style="CardTitle.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))

        ttk.Label(self._task_page, text="内容类型", style="FieldLabel.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 5)
        )
        kind_row = ttk.Frame(self._task_page, style="Card.TFrame")
        kind_row.grid(row=3, column=0, sticky="ew")
        for column in range(3):
            kind_row.columnconfigure(column, weight=1, uniform="kind")
        self.kind_buttons: dict[str, tk.Button] = {}
        labels = {
            "post": "01\n单个帖子",
            "user": "02\n创作者内容",
            "shop": "03\nShop 商品",
        }
        for column, (kind, label) in enumerate(labels.items()):
            button = tk.Button(
                kind_row, text=label, command=lambda value=kind: self._select_kind(value),
                justify="left", anchor="w", relief="flat", bd=0, highlightthickness=1,
                padx=12, pady=6, font=(UI_FONT, 9), cursor="hand2",
            )
            button.grid(
                row=0, column=column, sticky="ew",
                padx=(0 if column == 0 else 4, 0 if column == 2 else 4),
            )
            self.kind_buttons[kind] = button

        ttk.Label(self._task_page, text="目标地址", style="FieldLabel.TLabel").grid(
            row=4, column=0, sticky="w", pady=(12, 5)
        )
        self.url_entry = ttk.Entry(
            self._task_page, textvariable=self.url_var, font=(MONO_FONT, 10)
        )
        self.url_entry.grid(row=5, column=0, sticky="ew")
        ttk.Label(
            self._task_page, textvariable=self.kind_description_var,
            style="Muted.TLabel", wraplength=530, justify="left",
        ).grid(row=6, column=0, sticky="w", pady=(7, 0))

        date_panel = ttk.Frame(self._task_page, padding=(14, 10), style="Subtle.TFrame")
        date_panel.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        date_panel.columnconfigure(0, weight=2)
        date_panel.columnconfigure(1, weight=3)
        date_panel.columnconfigure(2, weight=3)
        date_intro = ttk.Frame(date_panel, style="Subtle.TFrame")
        date_intro.grid(row=0, column=0, sticky="nw", padx=(0, 10))
        ttk.Label(date_intro, text="发布时间范围", style="Subtle.TLabel").pack(anchor="w")
        ttk.Label(
            date_intro, text="留空不限\n单帖不应用",
            style="SubtleMuted.TLabel", justify="left",
        ).pack(anchor="w", pady=(2, 0))
        from_field = ttk.Frame(date_panel, style="Subtle.TFrame")
        from_field.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        ttk.Label(from_field, text="起始日期", style="SubtleMuted.TLabel").pack(anchor="w")
        self._date_picker_widget(from_field, self.date_from_var).pack(
            fill="x", pady=(5, 0)
        )
        to_field = ttk.Frame(date_panel, style="Subtle.TFrame")
        to_field.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        ttk.Label(to_field, text="结束日期", style="SubtleMuted.TLabel").pack(anchor="w")
        self._date_picker_widget(to_field, self.date_to_var).pack(fill="x", pady=(5, 0))

        actions = ttk.Frame(self._task_page, style="Card.TFrame")
        actions.grid(row=9, column=0, sticky="sew", pady=(12, 0))
        ttk.Label(
            actions, text="开始时自动保存当前配置", style="Muted.TLabel"
        ).pack(side="left")
        self.stop_btn = ttk.Button(
            actions, text="停止", command=self._on_stop,
            state="disabled", style="Danger.TButton",
        )
        self.stop_btn.pack(side="right")
        self.start_btn = ttk.Button(
            actions, text="开始下载  →", command=self._on_start, style="Accent.TButton"
        )
        self.start_btn.pack(side="right", padx=(0, 8))

    def _select_kind(self, kind: str) -> None:
        self.kind_var.set(KINDS[kind])
        placeholder, description = KIND_COPY[kind]
        self.kind_placeholder_var.set(placeholder)
        self.kind_description_var.set(f"输入：{placeholder}。{description}")
        for value, button in self.kind_buttons.items():
            selected = value == kind
            button.configure(
                bg=COLORS["accent_soft"] if selected else COLORS["surface_alt"],
                fg=COLORS["text"] if selected else COLORS["muted"],
                activebackground=COLORS["accent_soft"] if selected else "#202C3B",
                activeforeground=COLORS["text"],
                highlightbackground=COLORS["accent"] if selected else COLORS["border"],
                highlightcolor=COLORS["accent"] if selected else COLORS["border"],
            )

    def _build_settings_page(self, parent: ttk.Frame) -> None:
        self._settings_page = ttk.Frame(parent, padding=(20, 16), style="Card.TFrame")
        self._settings_page.grid(row=0, column=0, sticky="nsew")
        self._settings_page.columnconfigure(0, weight=1)
        self._settings_page.rowconfigure(5, weight=1)

        ttk.Label(
            self._settings_page, text="下载与存储", style="CardTitle.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self._settings_page, text="访问凭据、输出位置与下载策略", style="Muted.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        essentials = ttk.Frame(self._settings_page, style="Card.TFrame")
        essentials.grid(row=2, column=0, sticky="ew")
        essentials.columnconfigure(0, weight=1, uniform="essential")
        essentials.columnconfigure(1, weight=1, uniform="essential")

        cookie_field = ttk.Frame(essentials, style="Card.TFrame")
        cookie_field.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        cookie_field.columnconfigure(0, weight=1)
        ttk.Label(cookie_field, text="访问凭据", style="FieldLabel.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        cookie_field.columnconfigure(0, weight=1)
        cookie_entry = ttk.Entry(
            cookie_field, textvariable=self.cookie_var, show="●",
            font=(MONO_FONT, 9), style="Compact.TEntry",
        )
        cookie_entry.grid(row=1, column=0, sticky="ew")
        ttk.Checkbutton(
            cookie_field, text="显示", variable=self.cookie_visible_var,
            command=lambda: cookie_entry.configure(
                show="" if self.cookie_visible_var.get() else "●"
            ),
            style="Card.TCheckbutton",
        ).grid(row=1, column=1, padx=(7, 0))

        out_frame = ttk.Frame(essentials, style="Card.TFrame")
        out_frame.grid(row=0, column=1, sticky="ew", padx=(7, 0))
        out_frame.columnconfigure(0, weight=1)
        ttk.Label(out_frame, text="输出目录", style="FieldLabel.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        ttk.Entry(
            out_frame, textvariable=self.output_dir_var, style="Compact.TEntry"
        ).grid(
            row=1, column=0, sticky="ew"
        )
        ttk.Button(
            out_frame, text="选择", command=self._browse_output_dir,
            style="Compact.TButton",
        ).grid(row=1, column=1, padx=(6, 0))

        tuning = ttk.Frame(self._settings_page, padding=(14, 10), style="Subtle.TFrame")
        tuning.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        for column in range(3):
            tuning.columnconfigure(column, weight=1, uniform="tuning")
        numeric_fields = (
            ("请求间隔 / 秒", self.delay_var),
            ("最大重试", self.retries_var),
            ("并发下载数", self.workers_var),
        )
        for column, (label, variable) in enumerate(numeric_fields):
            field = ttk.Frame(tuning, style="Subtle.TFrame")
            field.grid(
                row=0, column=column, sticky="ew",
                padx=(0 if column == 0 else 6, 0 if column == 2 else 6),
            )
            ttk.Label(field, text=label, style="SubtleMuted.TLabel").pack(anchor="w")
            ttk.Entry(
                field, textvariable=variable, style="Compact.TEntry"
            ).pack(fill="x", pady=(4, 0))

        options = ttk.Frame(self._settings_page, padding=(14, 9), style="Subtle.TFrame")
        options.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Checkbutton(
            options, text="输出 info.json 元数据", variable=self.info_json_var
        ).grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Checkbutton(
            options, text="启用多线程下载", variable=self.threading_var
        ).grid(row=0, column=1, sticky="w", padx=(0, 18))
        ttk.Checkbutton(
            options, text="哈希去重", variable=self.skip_existing_var
        ).grid(row=0, column=2, sticky="w")

        format_frame = ttk.Frame(self._settings_page, style="Card.TFrame")
        format_frame.grid(row=6, column=0, sticky="sew", pady=(12, 0))
        format_frame.columnconfigure(0, weight=1)
        ttk.Label(format_frame, text="帖子目录格式", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            format_frame,
            text="可用：{yyyy} {mm} {dd} {date} {title} {author} {id}",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 7))
        ttk.Entry(
            format_frame, textvariable=self.dir_format_var, style="Compact.TEntry"
        ).grid(
            row=2, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(
            format_frame, text="保存偏好", command=self._save_config,
            style="Accent.TButton",
        ).grid(row=2, column=1, sticky="e")

    def _build_activity_panel(self, parent: ttk.Frame) -> None:
        activity = ttk.Frame(parent, padding=(20, 20, 16, 16), style="Card.TFrame")
        activity.grid(row=0, column=1, sticky="nsew")
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(3, weight=1)

        header = ttk.Frame(activity, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="运行记录", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            header, text="清空", command=self._clear_log, style="Ghost.TButton"
        ).grid(row=0, column=1, sticky="e")
        ttk.Label(
            activity, text="下载进度和诊断信息会实时显示在这里。", style="Muted.TLabel",
            wraplength=340, justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(3, 14))

        self.activity_progress = ttk.Progressbar(
            activity, mode="indeterminate", style="Accent.Horizontal.TProgressbar"
        )
        self.activity_progress.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.activity_progress.grid_remove()

        log_frame = ttk.Frame(activity, style="Card.TFrame")
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame, state="disabled", wrap="word", font=(MONO_FONT, 9),
            bg=COLORS["input"], fg=COLORS["text"], insertbackground=COLORS["text"],
            selectbackground=COLORS["accent_soft"], relief="flat", bd=0,
            highlightthickness=1, highlightbackground=COLORS["border"],
            padx=13, pady=12, spacing1=2, spacing3=4,
        )
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self.log_text.tag_configure("info", foreground="#C7D0DB")
        self.log_text.tag_configure("success", foreground=COLORS["success"])
        self.log_text.tag_configure("error", foreground=COLORS["danger"])
        self.log_text.tag_configure("dim", foreground=COLORS["faint"])
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "READY  等待任务。Ctrl + Enter 可快速开始。\n", "dim")
        self.log_text.configure(state="disabled")

        ttk.Label(
            activity, text="日志仅保留在本次运行中", style="Muted.TLabel"
        ).grid(row=4, column=0, sticky="w", pady=(10, 0))

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "LOG  运行记录已清空。\n", "dim")
        self.log_text.configure(state="disabled")

    def _set_status(self, label: str, detail: str, color: str) -> None:
        self.status_var.set(label)
        self.status_detail_var.set(detail)
        self.status_dot.itemconfigure(self._status_dot_id, fill=color)

    # ── 日期选择 ─────────────────────────────────────────────────

    def _date_picker_widget(self, parent: tk.Widget, var: tk.StringVar) -> tk.Widget:
        """只读输入框 + 「日历」按钮：只能通过日历弹窗选择日期，禁止手动输入。

        点击输入框或「日历」按钮都会弹出日历；日历中的「清除」可清空该日期。
        """
        frame = ttk.Frame(parent, style="Subtle.TFrame")
        entry = ttk.Entry(
            frame, textvariable=var, width=10, state="readonly", style="Compact.TEntry"
        )
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Button-1>", lambda _e: self._open_picker(var))
        ttk.Button(
            frame, text="选择", width=4, style="Compact.TButton",
            command=lambda: self._open_picker(var),
        ).pack(side="left", padx=(6, 0))
        return frame

    def _open_picker(self, var: tk.StringVar) -> None:
        _DatePicker(self.root, initial=var.get(), on_select=var.set)

    # ── 配置读写 ─────────────────────────────────────────────────

    def _browse_config(self) -> None:
        path = filedialog.askopenfilename(
            title="选择配置文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if path:
            self.path_var.set(path)
            self._reload_config()

    def _reload_config(self) -> None:
        path = self.path_var.get().strip() or None
        try:
            self.config = Config.load(path)
        except (OSError, ValueError) as e:
            messagebox.showerror("加载失败", f"无法读取配置文件：{e}")
            return
        self._config_to_widgets()
        self._log(("success", f"已加载配置：{self.config.source_path or path or '(默认)'}"))

    def _config_to_widgets(self) -> None:
        cfg = self.config
        self.path_var.set(str(cfg.source_path) if cfg.source_path else self.path_var.get())
        self.cookie_var.set(cfg.cookie)
        self.output_dir_var.set(cfg.output_dir)
        self.delay_var.set(str(cfg.request_delay))
        self.retries_var.set(str(cfg.max_retries))
        self.dir_format_var.set(cfg.post_dir_format)
        self.info_json_var.set(cfg.output_info_json)
        self.threading_var.set(cfg.enable_threading)
        self.workers_var.set(str(cfg.max_workers))
        self.skip_existing_var.set(cfg.skip_existing)
        self.date_from_var.set(cfg.date_from)
        self.date_to_var.set(cfg.date_to)

    def _widgets_to_config(self) -> list[str]:
        """把界面值写入 self.config，返回错误列表（为空表示成功）。"""
        cfg = self.config
        errors: list[str] = []

        def parse_float(name: str, value: str) -> float | None:
            try:
                return float(value)
            except ValueError:
                errors.append(f"{name} 必须是数字，当前值：{value!r}")
                return None

        def parse_int(name: str, value: str, minimum: int = 1) -> int | None:
            try:
                num = int(value)
            except ValueError:
                errors.append(f"{name} 必须是整数，当前值：{value!r}")
                return None
            if num < minimum:
                errors.append(f"{name} 不能小于 {minimum}")
                return None
            return num

        cfg.cookie = self.cookie_var.get()
        cfg.output_dir = self.output_dir_var.get().strip() or "./downloads"
        delay = parse_float("请求间隔", self.delay_var.get())
        retries = parse_int("最大重试次数", self.retries_var.get())
        workers = parse_int("并发下载数", self.workers_var.get())
        if errors:
            return errors
        cfg.request_delay = delay
        cfg.max_retries = retries
        cfg.post_dir_format = self.dir_format_var.get().strip() or "{yyyy}-{mm}-{dd}_{title}"
        cfg.output_info_json = self.info_json_var.get()
        cfg.enable_threading = self.threading_var.get()
        cfg.max_workers = workers
        cfg.skip_existing = self.skip_existing_var.get()
        cfg.date_from = self.date_from_var.get().strip()
        cfg.date_to = self.date_to_var.get().strip()
        return errors

    def _save_config(self) -> bool:
        """把界面上的配置写回配置文件。成功返回 True。"""
        errors = self._widgets_to_config()
        if errors:
            messagebox.showerror("配置无效", "\n".join(errors))
            return False
        errors = self.config.validate()
        if errors:
            messagebox.showerror("配置无效", "\n".join(errors))
            return False
        path = self.path_var.get().strip() or None
        try:
            saved = self.config.save(path)
        except OSError as e:
            messagebox.showerror("保存失败", f"无法写入配置文件：{e}")
            return False
        self.path_var.set(str(saved))
        self._set_status("配置已保存", str(saved), COLORS["success"])
        self._log(("success", f"配置已保存到 {saved}"))
        return True

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir_var.set(path)

    # ── 下载任务 ─────────────────────────────────────────────────

    def _on_start(self) -> None:
        if self._running:
            return
        if not self._save_config():
            return

        url = self.url_var.get().strip()
        kind = KIND_LABELS[self.kind_var.get()]
        if not url:
            messagebox.showerror("缺少 URL", "请输入帖子 URL/ID 或创作者链接")
            return

        self._cancel_event.clear()
        self._running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.activity_progress.grid()
        self.activity_progress.start(12)
        self._set_status("正在归档", KINDS[kind], COLORS["accent"])
        self._worker = threading.Thread(
            target=self._worker_run, args=(kind, url, self.config), daemon=True
        )
        self._worker.start()

    def _on_stop(self) -> None:
        if not self._running:
            return
        self._cancel_event.set()
        self.stop_btn.configure(state="disabled")
        self._log(("info", "正在停止…（当前文件下载完成后停止）"))
        self._set_status("正在停止", "等待当前文件处理完成", COLORS["warning"])

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise CancelledError()

    def _worker_run(self, kind: str, url: str, config: Config) -> None:
        old_console = downloader.console
        downloader.console = self._gui_console
        try:
            if kind == "post":
                self._run_post(url, config)
            elif kind == "user":
                self._run_user(url, config)
            else:
                self._run_shop(url, config)
        except CancelledError:
            self._log(("info", "已停止（用户取消）"))
        except Exception as e:
            self._log(("error", f"错误：{e}"))
            import traceback
            self._log(("error", traceback.format_exc().strip()))
        finally:
            downloader.console = old_console
            self.root.after(0, self._on_worker_finished)

    def _on_worker_finished(self) -> None:
        self._running = False
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.activity_progress.stop()
        self.activity_progress.grid_remove()
        self._set_status("就绪", "等待新的下载任务", COLORS["success"])

    def _new_registry(self, config: Config) -> HashRegistry | None:
        if not config.skip_existing:
            return None
        out = Path(config.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        return HashRegistry(out)

    def _run_post(self, url: str, config: Config) -> None:
        post_id = extract_post_id(url) if "/" in url else url
        if not post_id or not post_id.isdigit():
            self._log(("error", f"无法从 URL 中提取帖子 ID：{url}"))
            return

        client = PatreonClient(config)
        self._log(("info", f"正在获取帖子 {post_id} …"))
        post = client.fetch_post(post_id)
        self._log(("info", f"标题：{post.title or '(无标题)'}"))

        registry = self._new_registry(config)
        count = download_post(
            post, Path(config.output_dir), config,
            use_author_dir=False, registry=registry,
            cancel_event=self._cancel_event,
        )
        if registry:
            registry.save()
        self._log(("success", f"完成！共下载 {count} 个文件"))

    def _run_user(self, url: str, config: Config) -> None:
        user_info = extract_user_info(url)
        if not user_info:
            self._log(("error", f"无法从 URL 中提取创作者信息：{url}"))
            return

        client = PatreonClient(config)
        self._log(("info", f"正在解析创作者 {user_info['value']} …"))
        initial = client.get_initial_data(user_info["value"])
        campaign_id = initial.get("campaign_id")
        if not campaign_id:
            self._log(("error", f"未找到 campaign ID（HTTP {initial.get('http_status', '?')}），请检查 Cookie 是否有效"))
            return

        author_name = initial.get("author_name", user_info["value"])
        self._log(("info", f"创作者：{author_name}（campaign {campaign_id}）"))
        if config.date_from or config.date_to:
            self._log((
                "info",
                f"时间过滤：{config.date_from or '不限'} ~ {config.date_to or '不限'}",
            ))

        def on_page(loaded: int, total: int) -> None:
            self._check_cancelled()
            self._log(("info", f"  已获取 {loaded}/{total} 篇帖子 …"))

        posts = client.fetch_all_posts(campaign_id, initial.get("current_user_id"), on_page=on_page)
        self._log(("info", f"共找到 {len(posts)} 篇帖子，开始下载 …"))

        registry = self._new_registry(config)
        output_dir = Path(config.output_dir)
        total_files = 0
        for i, post in enumerate(posts, 1):
            self._check_cancelled()
            self._log(("info", f"[{i}/{len(posts)}] {post.title or post.id}"))
            total_files += download_post(
                post, output_dir, config, author_name=author_name,
                registry=registry, cancel_event=self._cancel_event,
            )
        if registry:
            registry.save()
        self._log(("success", f"完成！从 {len(posts)} 篇帖子共下载 {total_files} 个文件"))

    def _run_shop(self, url: str, config: Config) -> None:
        user_info = extract_user_info(url)
        if not user_info:
            self._log(("error", f"无法从 URL 中提取创作者信息：{url}"))
            return

        client = PatreonClient(config)
        self._log(("info", f"正在解析创作者 {user_info['value']} …"))
        initial = client.get_initial_data(user_info["value"])
        campaign_id = initial.get("campaign_id")
        if not campaign_id:
            self._log(("error", f"未找到 campaign ID（HTTP {initial.get('http_status', '?')}），请检查 Cookie 是否有效"))
            return

        author_name = initial.get("author_name", user_info["value"])
        self._log(("info", f"创作者：{author_name}（campaign {campaign_id}）"))
        if config.date_from or config.date_to:
            self._log((
                "info",
                f"时间过滤：{config.date_from or '不限'} ~ {config.date_to or '不限'}",
            ))

        def on_page(loaded: int) -> None:
            self._check_cancelled()
            self._log(("info", f"  已获取 {loaded} 件商品 …"))

        products = client.fetch_all_products(campaign_id, on_page=on_page)
        self._log(("info", f"共找到 {len(products)} 件商品，开始下载 …"))

        registry = self._new_registry(config)
        output_dir = Path(config.output_dir)
        total_files = 0
        for i, product in enumerate(products, 1):
            self._check_cancelled()
            self._log(("info", f"[{i}/{len(products)}] {product.name or product.id}"))
            total_files += download_product(
                product, output_dir, config, author_name=author_name,
                registry=registry, cancel_event=self._cancel_event,
            )
        if registry:
            registry.save()
        self._log(("success", f"完成！从 {len(products)} 件商品共下载 {total_files} 个文件"))

    # ── 日志 ─────────────────────────────────────────────────────

    def _log(self, entry: tuple[str, str]) -> None:
        self._log_queue.put(entry)

    def _poll_log(self) -> None:
        try:
            while True:
                tag, text = self._log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", text + "\n", tag)
                self.log_text.configure(state="disabled")
                self.log_text.see("end")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askyesno(
                "正在运行", "下载仍在进行，确定要停止并退出吗？"
            ):
                return
            self._cancel_event.set()
            self.root.destroy()
            return
        self.root.destroy()


def main(config_path: str | None = None) -> None:
    # Windows 默认会对 tkinter 做位图缩放；在创建根窗口前声明 DPI 感知，
    # 避免高分屏上出现字体发虚、窗口尺寸超出可用区域的问题。
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    PatreonGUI(root, config_path)
    root.mainloop()


if __name__ == "__main__":
    main()
