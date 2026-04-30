import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import asyncio
import json
import os
import time
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


@dataclass
class FileState:
    path: str
    stem: str = ""
    phase: str = "idle"
    error: str = ""
    result: Optional[Dict] = None
    start_time: float = 0.0
    end_time: float = 0.0
    quality_score: float = 0.0

    def __post_init__(self):
        if not self.stem:
            self.stem = Path(self.path).stem


class ColorTheme:
    BG_DARK = "#1a1a2e"
    BG_MID = "#16213e"
    BG_LIGHT = "#0f3460"
    BG_CARD = "#1e2a4a"
    BG_CARD_HOVER = "#253356"
    ACCENT = "#e94560"
    ACCENT2 = "#0ea5e9"
    ACCENT3 = "#8b5cf6"
    GREEN = "#22c55e"
    YELLOW = "#eab308"
    ORANGE = "#f97316"
    RED = "#ef4444"
    TEXT_PRIMARY = "#f1f5f9"
    TEXT_SECONDARY = "#94a3b8"
    TEXT_MUTED = "#64748b"
    BORDER = "#334155"
    SUCCESS = "#22c55e"
    WARNING = "#f97316"
    ERROR = "#ef4444"
    PIPELINE_IDLE = "#475569"
    PIPELINE_ACTIVE = "#3b82f6"
    PIPELINE_DONE = "#22c55e"
    PIPELINE_ERROR = "#ef4444"

    @classmethod
    def phase_color(cls, phase: str) -> str:
        return {
            "idle": cls.PIPELINE_IDLE,
            "parsing": cls.ACCENT2,
            "preprocessing": cls.ACCENT3,
            "extracting": cls.ACCENT,
            "done": cls.GREEN,
            "error": cls.RED,
        }.get(phase, cls.PIPELINE_IDLE)

    @classmethod
    def confidence_color(cls, conf: str) -> str:
        return {
            "high": cls.GREEN,
            "medium": cls.YELLOW,
            "low": cls.RED,
        }.get(conf, cls.TEXT_MUTED)

    @classmethod
    def quality_gradient(cls, score: float) -> str:
        if score >= 0.8:
            return cls.GREEN
        elif score >= 0.6:
            return cls.YELLOW
        elif score >= 0.4:
            return cls.ORANGE
        return cls.RED


class PipelineNode:
    def __init__(self, canvas: tk.Canvas, x: float, y: float, label: str, icon: str = ""):
        self.canvas = canvas
        self.x = x
        self.y = y
        self.label = label
        self.icon = icon
        self.radius = 22
        self.state = "idle"
        self.items = []
        self._draw()

    def _draw(self):
        for item in self.items:
            self.canvas.delete(item)
        self.items.clear()

        color = ColorTheme.phase_color(self.state)
        outline = color if self.state != "idle" else ColorTheme.BORDER

        shadow = self.canvas.create_oval(
            self.x - self.radius + 2, self.y - self.radius + 2,
            self.x + self.radius + 2, self.y + self.radius + 2,
            fill="#000000", outline="", stipple="gray25"
        )
        self.items.append(shadow)

        circle = self.canvas.create_oval(
            self.x - self.radius, self.y - self.radius,
            self.x + self.radius, self.y + self.radius,
            fill=ColorTheme.BG_CARD if self.state == "idle" else color,
            outline=outline, width=2
        )
        self.items.append(circle)

        if self.icon:
            icon_item = self.canvas.create_text(
                self.x, self.y - 2, text=self.icon,
                fill=ColorTheme.TEXT_PRIMARY if self.state != "idle" else ColorTheme.TEXT_MUTED,
                font=("Segoe UI Emoji", 11)
            )
            self.items.append(icon_item)

        label_item = self.canvas.create_text(
            self.x, self.y + self.radius + 14, text=self.label,
            fill=ColorTheme.TEXT_PRIMARY if self.state != "idle" else ColorTheme.TEXT_MUTED,
            font=("Microsoft YaHei UI", 9)
        )
        self.items.append(label_item)

    def set_state(self, state: str):
        self.state = state
        self._draw()


class PipelineVisualizer:
    def __init__(self, canvas: tk.Canvas):
        self.canvas = canvas
        self.nodes: List[PipelineNode] = []
        self.edges: List[int] = []
        self._build()

    def _build(self):
        self.canvas.update_idletasks()
        w = self.canvas.winfo_width() or self.canvas.winfo_reqwidth() or 800
        cx = w / 2
        cy = 50
        n_stages = 8
        spacing = min(130, max(80, (w - 100) / (n_stages - 1)))

        stages = [
            ("PDF", "📄"), ("解析", "⚙️"), ("预处理", "🔬"),
            ("规则提取", "📏"), ("LLM增强", "🤖"), ("VLM增强", "👁️"),
            ("交叉验证", "✓"), ("输出", "📋")
        ]

        total_width = (len(stages) - 1) * spacing
        start_x = cx - total_width / 2

        for i, (label, icon) in enumerate(stages):
            x = start_x + i * spacing
            node = PipelineNode(self.canvas, x, cy, label, icon)
            self.nodes.append(node)

            if i > 0:
                prev = self.nodes[i - 1]
                edge = self.canvas.create_line(
                    prev.x + prev.radius + 4, prev.y,
                    x - node.radius - 4, node.y,
                    fill=ColorTheme.BORDER, width=2, dash=(4, 4)
                )
                self.edges.append(edge)

    def set_stage(self, stage_idx: int, state: str):
        if 0 <= stage_idx < len(self.nodes):
            self.nodes[stage_idx].set_state(state)
            if stage_idx > 0 and state not in ("idle",):
                prev_idx = stage_idx - 1
                if self.nodes[prev_idx].state == "done":
                    edge_idx = stage_idx - 1
                    if edge_idx < len(self.edges):
                        self.canvas.itemconfig(
                            self.edges[edge_idx],
                            fill=ColorTheme.PIPELINE_DONE, dash=()
                        )

    def reset(self):
        for node in self.nodes:
            node.set_state("idle")
        for edge in self.edges:
            self.canvas.itemconfig(edge, fill=ColorTheme.BORDER, dash=(4, 4))

    def set_all_done(self):
        for i, node in enumerate(self.nodes):
            node.set_state("done")
            if i > 0:
                edge_idx = i - 1
                if edge_idx < len(self.edges):
                    self.canvas.itemconfig(
                        self.edges[edge_idx],
                        fill=ColorTheme.PIPELINE_DONE, dash=()
                    )


class QualityRing:
    def __init__(self, canvas: tk.Canvas, x: float, y: float, radius: float = 40):
        self.canvas = canvas
        self.x = x
        self.y = y
        self.radius = radius
        self.items = []
        self._score = 0.0
        self._draw(0.0)

    def _draw(self, score: float):
        for item in self.items:
            self.canvas.delete(item)
        self.items.clear()

        bg_oval = self.canvas.create_oval(
            self.x - self.radius, self.y - self.radius,
            self.x + self.radius, self.y + self.radius,
            fill=ColorTheme.BG_DARK, outline=ColorTheme.BORDER, width=2
        )
        self.items.append(bg_oval)

        color = ColorTheme.quality_gradient(score)
        pct = score
        if pct > 0:
            extent = pct * 360
            arc = self.canvas.create_arc(
                self.x - self.radius + 4, self.y - self.radius + 4,
                self.x + self.radius - 4, self.y + self.radius - 4,
                start=90, extent=-extent,
                fill=color, outline=color, style=tk.CHORD
            )
            self.items.append(arc)

        inner_r = self.radius - 10
        inner = self.canvas.create_oval(
            self.x - inner_r, self.y - inner_r,
            self.x + inner_r, self.y + inner_r,
            fill=ColorTheme.BG_DARK, outline=""
        )
        self.items.append(inner)

        pct_text = f"{int(score * 100)}%"
        text = self.canvas.create_text(
            self.x, self.y, text=pct_text,
            fill=color, font=("Microsoft YaHei UI", 12, "bold")
        )
        self.items.append(text)

    def update_score(self, score: float):
        self._score = score
        self._draw(score)


class NanozymeDashboard:
    PIPELINE_STAGES = ["idle", "parsing", "preprocessing", "extracting", "done", "error"]
    STAGE_LABELS = {
        "idle": "就绪", "parsing": "解析PDF", "preprocessing": "预处理",
        "extracting": "智能提取", "done": "完成", "error": "错误"
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NanozymeExtractor v2 — 纳米酶智能提取仪表板")
        self.root.geometry("1400x900")
        self.root.minsize(1200, 800)
        self.root.configure(bg=ColorTheme.BG_DARK)

        self.files: List[FileState] = []
        self.stop_event = threading.Event()
        self._running = False
        self._selected_idx: Optional[int] = None
        self._start_time = 0.0
        self._anim_id = None

        self._setup_styles()
        self._build_ui()
        self._setup_logging()
        self._load_config()

    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.style.configure("Dark.TFrame", background=ColorTheme.BG_DARK)
        self.style.configure("Mid.TFrame", background=ColorTheme.BG_MID)
        self.style.configure("Card.TFrame", background=ColorTheme.BG_CARD)
        self.style.configure("Dark.TLabel", background=ColorTheme.BG_DARK, foreground=ColorTheme.TEXT_PRIMARY,
                             font=("Microsoft YaHei UI", 10))
        self.style.configure("Title.TLabel", background=ColorTheme.BG_DARK, foreground=ColorTheme.TEXT_PRIMARY,
                             font=("Microsoft YaHei UI", 18, "bold"))
        self.style.configure("Subtitle.TLabel", background=ColorTheme.BG_DARK, foreground=ColorTheme.TEXT_SECONDARY,
                             font=("Microsoft YaHei UI", 11))
        self.style.configure("CardTitle.TLabel", background=ColorTheme.BG_CARD, foreground=ColorTheme.TEXT_PRIMARY,
                             font=("Microsoft YaHei UI", 11, "bold"))
        self.style.configure("CardField.TLabel", background=ColorTheme.BG_CARD, foreground=ColorTheme.TEXT_SECONDARY,
                             font=("Microsoft YaHei UI", 9))
        self.style.configure("CardValue.TLabel", background=ColorTheme.BG_CARD, foreground=ColorTheme.TEXT_PRIMARY,
                             font=("Microsoft YaHei UI", 10, "bold"))
        self.style.configure("Status.TLabel", background=ColorTheme.BG_DARK, foreground=ColorTheme.TEXT_MUTED,
                             font=("Microsoft YaHei UI", 9))
        self.style.configure("Metric.TLabel", background=ColorTheme.BG_CARD, foreground=ColorTheme.TEXT_PRIMARY,
                             font=("Microsoft YaHei UI", 20, "bold"))
        self.style.configure("MetricLabel.TLabel", background=ColorTheme.BG_CARD, foreground=ColorTheme.TEXT_MUTED,
                             font=("Microsoft YaHei UI", 9))
        self.style.configure("Accent.TButton", font=("Microsoft YaHei UI", 12, "bold"), padding=12)
        self.style.configure("Small.TButton", font=("Microsoft YaHei UI", 9), padding=4)

        self.style.map("Treeview",
                       background=[("selected", ColorTheme.ACCENT2)],
                       foreground=[("selected", ColorTheme.TEXT_PRIMARY)])

    def _build_ui(self):
        self._build_topbar()

        body = tk.Frame(self.root, bg=ColorTheme.BG_DARK)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        self._build_sidebar(body)

        center = tk.Frame(body, bg=ColorTheme.BG_DARK)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))
        self._build_pipeline_panel(center)
        self._build_result_area(center)

        self._build_bottombar()

    def _build_topbar(self):
        topbar = tk.Frame(self.root, bg=ColorTheme.BG_MID, height=56)
        topbar.pack(fill=tk.X)
        topbar.pack_propagate(False)

        left = tk.Frame(topbar, bg=ColorTheme.BG_MID)
        left.pack(side=tk.LEFT, padx=16, fill=tk.Y)

        tk.Label(left, text="🧬 NanozymeExtractor", bg=ColorTheme.BG_MID,
                 fg=ColorTheme.TEXT_PRIMARY, font=("Microsoft YaHei UI", 15, "bold")).pack(side=tk.LEFT, pady=12)
        tk.Label(left, text="v2.0", bg=ColorTheme.BG_MID,
                 fg=ColorTheme.ACCENT2, font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(6, 0), pady=12)

        right = tk.Frame(topbar, bg=ColorTheme.BG_MID)
        right.pack(side=tk.RIGHT, padx=16, fill=tk.Y)

        self.api_llm_dot = tk.Label(right, text="● LLM", bg=ColorTheme.BG_MID,
                                    fg=ColorTheme.TEXT_MUTED, font=("Microsoft YaHei UI", 9))
        self.api_llm_dot.pack(side=tk.LEFT, padx=(0, 12), pady=12)

        self.api_vlm_dot = tk.Label(right, text="● VLM", bg=ColorTheme.BG_MID,
                                    fg=ColorTheme.TEXT_MUTED, font=("Microsoft YaHei UI", 9))
        self.api_vlm_dot.pack(side=tk.LEFT, padx=(0, 12), pady=12)

        self.clock_label = tk.Label(right, text="", bg=ColorTheme.BG_MID,
                                    fg=ColorTheme.TEXT_MUTED, font=("Consolas", 9))
        self.clock_label.pack(side=tk.LEFT, pady=12)
        self._tick_clock()

    def _tick_clock(self):
        if hasattr(self, '_start_time') and self._start_time > 0 and self._running:
            elapsed = time.time() - self._start_time
            m, s = divmod(int(elapsed), 60)
            self.clock_label.config(text=f"⏱ {m:02d}:{s:02d}")
        else:
            self.clock_label.config(text="")
        self.root.after(1000, self._tick_clock)

    def _build_sidebar(self, parent):
        sidebar = tk.Frame(parent, bg=ColorTheme.BG_MID, width=320)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        drop_frame = tk.Frame(sidebar, bg=ColorTheme.BG_MID, padx=12, pady=8)
        drop_frame.pack(fill=tk.X)

        self.drop_zone = tk.Canvas(drop_frame, height=80, bg=ColorTheme.BG_CARD,
                                   highlightthickness=2, highlightbackground=ColorTheme.BORDER,
                                   highlightcolor=ColorTheme.ACCENT2)
        self.drop_zone.pack(fill=tk.X)
        self.drop_zone.create_text(
            150, 28, text="📂 拖入PDF或点击选择",
            fill=ColorTheme.TEXT_SECONDARY, font=("Microsoft YaHei UI", 11),
            tags="drop_text"
        )
        self.drop_zone.create_text(
            150, 52, text="支持多文件 / 文件夹批量导入",
            fill=ColorTheme.TEXT_MUTED, font=("Microsoft YaHei UI", 8),
            tags="drop_hint"
        )
        self.drop_zone.bind("<Button-1>", lambda e: self._select_files())
        self.drop_zone.bind("<Enter>", lambda e: self.drop_zone.config(
            highlightbackground=ColorTheme.ACCENT2))
        self.drop_zone.bind("<Leave>", lambda e: self.drop_zone.config(
            highlightbackground=ColorTheme.BORDER))

        btn_row = tk.Frame(sidebar, bg=ColorTheme.BG_MID, padx=12)
        btn_row.pack(fill=tk.X, pady=(0, 4))
        tk.Button(btn_row, text="📁 选择文件", bg=ColorTheme.BG_CARD, fg=ColorTheme.TEXT_PRIMARY,
                  font=("Microsoft YaHei UI", 9), relief=tk.FLAT, padx=8, pady=4,
                  activebackground=ColorTheme.BG_CARD_HOVER, activeforeground=ColorTheme.TEXT_PRIMARY,
                  command=self._select_files).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(btn_row, text="📂 选择文件夹", bg=ColorTheme.BG_CARD, fg=ColorTheme.TEXT_PRIMARY,
                  font=("Microsoft YaHei UI", 9), relief=tk.FLAT, padx=8, pady=4,
                  activebackground=ColorTheme.BG_CARD_HOVER, activeforeground=ColorTheme.TEXT_PRIMARY,
                  command=self._select_folder).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(btn_row, text="🗑 清空", bg=ColorTheme.BG_CARD, fg=ColorTheme.TEXT_MUTED,
                  font=("Microsoft YaHei UI", 9), relief=tk.FLAT, padx=8, pady=4,
                  activebackground=ColorTheme.BG_CARD_HOVER, activeforeground=ColorTheme.TEXT_PRIMARY,
                  command=self._clear_files).pack(side=tk.RIGHT)

        list_frame = tk.Frame(sidebar, bg=ColorTheme.BG_MID, padx=12)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        tk.Label(list_frame, text="文件队列", bg=ColorTheme.BG_MID,
                 fg=ColorTheme.TEXT_MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W, pady=(0, 4))

        tree_frame = tk.Frame(list_frame, bg=ColorTheme.BG_CARD)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.file_tree = ttk.Treeview(
            tree_frame, columns=("file", "status", "quality"), show="headings",
            height=10, selectmode="browse"
        )
        self.file_tree.heading("file", text="文件名")
        self.file_tree.heading("status", text="状态")
        self.file_tree.heading("quality", text="质量")
        self.file_tree.column("file", width=160, minwidth=120)
        self.file_tree.column("status", width=60, minwidth=50)
        self.file_tree.column("quality", width=50, minwidth=40)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=vsb.set)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_tree.bind("<<TreeviewSelect>>", self._on_file_select)

        self.file_count_label = tk.Label(sidebar, text="0 个文件", bg=ColorTheme.BG_MID,
                                         fg=ColorTheme.TEXT_MUTED, font=("Microsoft YaHei UI", 9))
        self.file_count_label.pack(padx=12, anchor=tk.W, pady=(0, 4))

        config_frame = tk.Frame(sidebar, bg=ColorTheme.BG_MID, padx=12)
        config_frame.pack(fill=tk.X, pady=(0, 8))

        self.llm_var = tk.BooleanVar(value=True)
        self.vlm_var = tk.BooleanVar(value=True)

        cb_frame = tk.Frame(config_frame, bg=ColorTheme.BG_MID)
        cb_frame.pack(fill=tk.X, pady=(0, 4))
        tk.Checkbutton(cb_frame, text="LLM增强", variable=self.llm_var,
                       bg=ColorTheme.BG_MID, fg=ColorTheme.TEXT_SECONDARY,
                       selectcolor=ColorTheme.BG_CARD, activebackground=ColorTheme.BG_MID,
                       activeforeground=ColorTheme.TEXT_PRIMARY,
                       font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 8))
        tk.Checkbutton(cb_frame, text="VLM增强", variable=self.vlm_var,
                       bg=ColorTheme.BG_MID, fg=ColorTheme.TEXT_SECONDARY,
                       selectcolor=ColorTheme.BG_CARD, activebackground=ColorTheme.BG_MID,
                       activeforeground=ColorTheme.TEXT_PRIMARY,
                       font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)

        self.run_btn = tk.Button(
            config_frame, text="▶  一键提取", bg=ColorTheme.ACCENT, fg="white",
            font=("Microsoft YaHei UI", 13, "bold"), relief=tk.FLAT, pady=10,
            activebackground="#c73e54", activeforeground="white",
            command=self._start_pipeline
        )
        self.run_btn.pack(fill=tk.X, pady=(0, 4))

        self.stop_btn = tk.Button(
            config_frame, text="⏹  停止", bg=ColorTheme.BG_CARD, fg=ColorTheme.TEXT_MUTED,
            font=("Microsoft YaHei UI", 10), relief=tk.FLAT, pady=6,
            state=tk.DISABLED, command=self._stop_pipeline
        )
        self.stop_btn.pack(fill=tk.X)

    def _build_pipeline_panel(self, parent):
        pipe_frame = tk.Frame(parent, bg=ColorTheme.BG_MID, height=110)
        pipe_frame.pack(fill=tk.X, pady=(0, 8))
        pipe_frame.pack_propagate(False)

        tk.Label(pipe_frame, text="提取管线", bg=ColorTheme.BG_MID,
                 fg=ColorTheme.TEXT_MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W, padx=12, pady=(6, 0))

        self.pipeline_canvas = tk.Canvas(pipe_frame, bg=ColorTheme.BG_MID, highlightthickness=0, height=80)
        self.pipeline_canvas.pack(fill=tk.X, padx=12, pady=(0, 6))

        self.pipeline_viz = None
        self.pipeline_canvas.bind("<Configure>", self._on_pipeline_resize)

    def _on_pipeline_resize(self, event=None):
        self.pipeline_canvas.delete("all")
        self.pipeline_viz = PipelineVisualizer(self.pipeline_canvas)

    def _build_result_area(self, parent):
        result_frame = tk.Frame(parent, bg=ColorTheme.BG_DARK)
        result_frame.pack(fill=tk.BOTH, expand=True)

        tab_bar = tk.Frame(result_frame, bg=ColorTheme.BG_DARK)
        tab_bar.pack(fill=tk.X, pady=(0, 4))

        self._tab_btns = {}
        tabs = [("result", "📋 提取结果"), ("analytics", "📊 批量分析"), ("log", "📝 运行日志")]
        for i, (tab_id, tab_text) in enumerate(tabs):
            btn = tk.Button(
                tab_bar, text=tab_text, bg=ColorTheme.BG_CARD if i == 0 else ColorTheme.BG_DARK,
                fg=ColorTheme.TEXT_PRIMARY if i == 0 else ColorTheme.TEXT_MUTED,
                font=("Microsoft YaHei UI", 10), relief=tk.FLAT, padx=16, pady=6,
                activebackground=ColorTheme.BG_CARD_HOVER, activeforeground=ColorTheme.TEXT_PRIMARY,
                command=lambda tid=tab_id: self._switch_tab(tid)
            )
            btn.pack(side=tk.LEFT, padx=(0, 2))
            self._tab_btns[tab_id] = btn

        self._tab_frames = {}
        for tab_id, _ in tabs:
            frame = tk.Frame(result_frame, bg=ColorTheme.BG_DARK)
            self._tab_frames[tab_id] = frame
        self._tab_frames["result"].pack(fill=tk.BOTH, expand=True)
        self._current_tab = "result"

        self._build_result_tab(self._tab_frames["result"])
        self._build_analytics_tab(self._tab_frames["analytics"])
        self._build_log_tab(self._tab_frames["log"])

    def _switch_tab(self, tab_id: str):
        for tid, frame in self._tab_frames.items():
            frame.pack_forget()
        self._tab_frames[tab_id].pack(fill=tk.BOTH, expand=True)
        for tid, btn in self._tab_btns.items():
            if tid == tab_id:
                btn.config(bg=ColorTheme.BG_CARD, fg=ColorTheme.TEXT_PRIMARY)
            else:
                btn.config(bg=ColorTheme.BG_DARK, fg=ColorTheme.TEXT_MUTED)
        self._current_tab = tab_id

    def _build_result_tab(self, parent):
        top_bar = tk.Frame(parent, bg=ColorTheme.BG_DARK)
        top_bar.pack(fill=tk.X, pady=(0, 6))

        self.result_title = tk.Label(top_bar, text="选择左侧文件查看结果", bg=ColorTheme.BG_DARK,
                                     fg=ColorTheme.TEXT_SECONDARY, font=("Microsoft YaHei UI", 12))
        self.result_title.pack(side=tk.LEFT)

        btn_frame = tk.Frame(top_bar, bg=ColorTheme.BG_DARK)
        btn_frame.pack(side=tk.RIGHT)
        tk.Button(btn_frame, text="💾 保存JSON", bg=ColorTheme.BG_CARD, fg=ColorTheme.TEXT_PRIMARY,
                  font=("Microsoft YaHei UI", 9), relief=tk.FLAT, padx=8, pady=4,
                  activebackground=ColorTheme.BG_CARD_HOVER,
                  command=self._save_result).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(btn_frame, text="📂 打开目录", bg=ColorTheme.BG_CARD, fg=ColorTheme.TEXT_PRIMARY,
                  font=("Microsoft YaHei UI", 9), relief=tk.FLAT, padx=8, pady=4,
                  activebackground=ColorTheme.BG_CARD_HOVER,
                  command=self._open_result_dir).pack(side=tk.LEFT)

        content = tk.Frame(parent, bg=ColorTheme.BG_DARK)
        content.pack(fill=tk.BOTH, expand=True)

        left_cards = tk.Frame(content, bg=ColorTheme.BG_DARK, width=420)
        left_cards.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        left_cards.pack_propagate(False)

        right_detail = tk.Frame(content, bg=ColorTheme.BG_DARK)
        right_detail.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_result_cards(left_cards)
        self._build_detail_panel(right_detail)

    def _build_result_cards(self, parent):
        canvas_frame = tk.Frame(parent, bg=ColorTheme.BG_DARK)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, bg=ColorTheme.BG_DARK, highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        self._card_inner = tk.Frame(canvas, bg=ColorTheme.BG_DARK)
        self._card_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._card_inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._result_canvas = canvas

        self._cards = {}

        card_defs = [
            ("material", "🧪 纳米酶材料", [
                ("name", "材料名称"), ("enzyme_type", "酶活性类型"),
                ("morphology", "形貌"), ("size", "尺寸"),
                ("crystal_structure", "晶体结构"), ("surface_area", "比表面积"),
                ("synthesis_method", "合成方法"),
            ]),
            ("kinetics", "⚡ 动力学参数", [
                ("Km", "Km"), ("Km_unit", "Km单位"),
                ("Vmax", "Vmax"), ("Vmax_unit", "Vmax单位"),
                ("kcat", "kcat"), ("kcat_unit", "kcat单位"),
            ]),
            ("conditions", "🔬 反应条件", [
                ("optimal_pH", "最适pH"), ("pH_range", "pH范围"),
                ("optimal_temp", "最适温度"), ("temp_range", "温度范围"),
                ("substrates", "底物"),
            ]),
            ("application", "🎯 应用", [
                ("app_type", "应用类型"), ("detection_limit", "检测限"),
                ("linear_range", "线性范围"), ("target", "检测目标"),
            ]),
        ]

        for card_id, card_title, fields in card_defs:
            card = tk.Frame(self._card_inner, bg=ColorTheme.BG_CARD, padx=12, pady=8)
            card.pack(fill=tk.X, pady=(0, 6))

            tk.Label(card, text=card_title, bg=ColorTheme.BG_CARD,
                     fg=ColorTheme.ACCENT2, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, pady=(0, 6))

            grid = tk.Frame(card, bg=ColorTheme.BG_CARD)
            grid.pack(fill=tk.X)
            grid.columnconfigure(1, weight=1)

            self._cards[card_id] = {}
            for i, (fid, flabel) in enumerate(fields):
                tk.Label(grid, text=flabel, bg=ColorTheme.BG_CARD,
                         fg=ColorTheme.TEXT_MUTED, font=("Microsoft YaHei UI", 9)).grid(
                    row=i, column=0, sticky=tk.W, pady=2, padx=(0, 8))
                val_label = tk.Label(grid, text="—", bg=ColorTheme.BG_CARD,
                                     fg=ColorTheme.TEXT_PRIMARY, font=("Microsoft YaHei UI", 10, "bold"),
                                     wraplength=300, anchor=tk.W, justify=tk.LEFT)
                val_label.grid(row=i, column=1, sticky=tk.W, pady=2)
                self._cards[card_id][fid] = val_label

    def _build_detail_panel(self, parent):
        quality_frame = tk.Frame(parent, bg=ColorTheme.BG_CARD, padx=12, pady=8)
        quality_frame.pack(fill=tk.X, pady=(0, 6))

        tk.Label(quality_frame, text="提取质量", bg=ColorTheme.BG_CARD,
                 fg=ColorTheme.ACCENT2, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, pady=(0, 6))

        q_content = tk.Frame(quality_frame, bg=ColorTheme.BG_CARD)
        q_content.pack(fill=tk.X)

        self.quality_canvas = tk.Canvas(q_content, width=90, height=90,
                                        bg=ColorTheme.BG_CARD, highlightthickness=0)
        self.quality_canvas.pack(side=tk.LEFT, padx=(0, 12))
        self.quality_ring = QualityRing(self.quality_canvas, 45, 45, 38)

        info_frame = tk.Frame(q_content, bg=ColorTheme.BG_CARD)
        info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.conf_label = tk.Label(info_frame, text="置信度: —", bg=ColorTheme.BG_CARD,
                                   fg=ColorTheme.TEXT_SECONDARY, font=("Microsoft YaHei UI", 10))
        self.conf_label.pack(anchor=tk.W, pady=2)

        self.status_detail_label = tk.Label(info_frame, text="状态: —", bg=ColorTheme.BG_CARD,
                                            fg=ColorTheme.TEXT_SECONDARY, font=("Microsoft YaHei UI", 10))
        self.status_detail_label.pack(anchor=tk.W, pady=2)

        self.warn_count_label = tk.Label(info_frame, text="警告: —", bg=ColorTheme.BG_CARD,
                                         fg=ColorTheme.TEXT_SECONDARY, font=("Microsoft YaHei UI", 10))
        self.warn_count_label.pack(anchor=tk.W, pady=2)

        diag_frame = tk.Frame(parent, bg=ColorTheme.BG_CARD, padx=12, pady=8)
        diag_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(diag_frame, text="诊断详情", bg=ColorTheme.BG_CARD,
                 fg=ColorTheme.ACCENT2, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, pady=(0, 6))

        self.diag_text = tk.Text(diag_frame, font=("Consolas", 9), wrap=tk.WORD,
                                 bg=ColorTheme.BG_DARK, fg=ColorTheme.TEXT_PRIMARY,
                                 insertbackground=ColorTheme.TEXT_PRIMARY,
                                 selectbackground=ColorTheme.ACCENT2,
                                 relief=tk.FLAT, padx=8, pady=6, state=tk.DISABLED)
        diag_vsb = ttk.Scrollbar(diag_frame, orient=tk.VERTICAL, command=self.diag_text.yview)
        self.diag_text.configure(yscrollcommand=diag_vsb.set)
        self.diag_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        diag_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.diag_text.tag_configure("warn", foreground=ColorTheme.YELLOW)
        self.diag_text.tag_configure("error", foreground=ColorTheme.RED)
        self.diag_text.tag_configure("ok", foreground=ColorTheme.GREEN)

    def _build_analytics_tab(self, parent):
        metrics_row = tk.Frame(parent, bg=ColorTheme.BG_DARK)
        metrics_row.pack(fill=tk.X, pady=(0, 8))

        self._metric_cards = {}
        metrics = [
            ("total", "总文件", "0"),
            ("success", "成功", "0"),
            ("failed", "失败", "0"),
            ("avg_quality", "平均质量", "—"),
            ("km_rate", "Km提取率", "—"),
            ("vmax_rate", "Vmax提取率", "—"),
        ]

        for i, (mid, mlabel, mdefault) in enumerate(metrics):
            card = tk.Frame(metrics_row, bg=ColorTheme.BG_CARD, padx=16, pady=10)
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4 if i < len(metrics) - 1 else 0))

            val_label = tk.Label(card, text=mdefault, bg=ColorTheme.BG_CARD,
                                 fg=ColorTheme.TEXT_PRIMARY, font=("Microsoft YaHei UI", 20, "bold"))
            val_label.pack()

            lbl = tk.Label(card, text=mlabel, bg=ColorTheme.BG_CARD,
                           fg=ColorTheme.TEXT_MUTED, font=("Microsoft YaHei UI", 9))
            lbl.pack()

            self._metric_cards[mid] = val_label

        chart_frame = tk.Frame(parent, bg=ColorTheme.BG_CARD, padx=12, pady=8)
        chart_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(chart_frame, text="字段提取率", bg=ColorTheme.BG_CARD,
                 fg=ColorTheme.ACCENT2, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, pady=(0, 8))

        self.analytics_canvas = tk.Canvas(chart_frame, bg=ColorTheme.BG_CARD, highlightthickness=0)
        self.analytics_canvas.pack(fill=tk.BOTH, expand=True)

    def _build_log_tab(self, parent):
        self.log_text = tk.Text(parent, font=("Consolas", 9), wrap=tk.WORD,
                                bg=ColorTheme.BG_DARK, fg=ColorTheme.TEXT_PRIMARY,
                                insertbackground=ColorTheme.TEXT_PRIMARY,
                                selectbackground=ColorTheme.ACCENT2,
                                relief=tk.FLAT, padx=8, pady=6, state=tk.DISABLED)
        log_vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_vsb.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text.tag_configure("INFO", foreground=ColorTheme.TEXT_SECONDARY)
        self.log_text.tag_configure("WARNING", foreground=ColorTheme.YELLOW)
        self.log_text.tag_configure("ERROR", foreground=ColorTheme.RED)
        self.log_text.tag_configure("SUCCESS", foreground=ColorTheme.GREEN)

    def _build_bottombar(self):
        bottom = tk.Frame(self.root, bg=ColorTheme.BG_MID, height=32)
        bottom.pack(fill=tk.X)
        bottom.pack_propagate(False)

        self.progress = ttk.Progressbar(bottom, mode="determinate", length=300)
        self.progress.pack(side=tk.LEFT, padx=(12, 8), fill=tk.X, expand=True, pady=6)

        self.progress_label = tk.Label(bottom, text="", bg=ColorTheme.BG_MID,
                                       fg=ColorTheme.TEXT_MUTED, font=("Microsoft YaHei UI", 9))
        self.progress_label.pack(side=tk.LEFT, padx=(0, 12), pady=6)

    def _setup_logging(self):
        handler = _DashboardLogHandler(self)
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)

    def _load_config(self):
        try:
            from config_manager import ConfigManager
            cm = ConfigManager()
            llm_cfg = cm.get_llm_config()
            vlm_cfg = cm.get_vlm_config()
            llm_ok = bool(llm_cfg and getattr(llm_cfg, 'api_key', None) and getattr(llm_cfg, 'base_url', None))
            vlm_ok = bool(vlm_cfg and getattr(vlm_cfg, 'api_key', None) and getattr(vlm_cfg, 'base_url', None))
            self.api_llm_dot.config(fg=ColorTheme.GREEN if llm_ok else ColorTheme.RED)
            self.api_vlm_dot.config(fg=ColorTheme.GREEN if vlm_ok else ColorTheme.RED)
        except Exception:
            try:
                import yaml
                cfg_path = Path("config.yaml")
                if cfg_path.exists():
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = yaml.safe_load(f)
                    providers = cfg.get("providers", {})
                    llm = providers.get("llm", {})
                    vlm = providers.get("vlm", {})
                    llm_ok = bool(llm.get("api_key") and llm.get("base_url"))
                    vlm_ok = bool(vlm.get("api_key") and vlm.get("base_url"))
                    self.api_llm_dot.config(fg=ColorTheme.GREEN if llm_ok else ColorTheme.RED)
                    self.api_vlm_dot.config(fg=ColorTheme.GREEN if vlm_ok else ColorTheme.RED)
                else:
                    self.api_llm_dot.config(fg=ColorTheme.RED)
                    self.api_vlm_dot.config(fg=ColorTheme.RED)
            except Exception:
                self.api_llm_dot.config(fg=ColorTheme.RED)
                self.api_vlm_dot.config(fg=ColorTheme.RED)

    def _select_files(self):
        paths = filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf")])
        for p in paths:
            if not any(f.path == p for f in self.files):
                self.files.append(FileState(path=p))
        self._refresh_file_tree()

    def _select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        for p in Path(folder).rglob("*.pdf"):
            if not any(f.path == str(p) for f in self.files):
                self.files.append(FileState(path=str(p)))
        self._refresh_file_tree()

    def _clear_files(self):
        self.files.clear()
        self._refresh_file_tree()
        self._clear_result_display()

    def _refresh_file_tree(self):
        self.file_tree.delete(*self.file_tree.get_children())
        for i, f in enumerate(self.files):
            status_text = self.STAGE_LABELS.get(f.phase, f.phase)
            quality_text = f"{int(f.quality_score * 100)}%" if f.quality_score > 0 else "—"
            if f.phase == "error":
                status_text = "错误"
                quality_text = "✗"
            elif f.phase == "done":
                quality_text = f"{int(f.quality_score * 100)}%"
            self.file_tree.insert("", tk.END, iid=str(i), values=(f.stem, status_text, quality_text))
        n = len(self.files)
        self.file_count_label.config(text=f"{n} 个文件" if n else "0 个文件")

    def _update_file_phase(self, idx: int, phase: str, error: str = ""):
        if 0 <= idx < len(self.files):
            self.files[idx].phase = phase
            self.files[idx].error = error
            self.root.after(0, lambda: self._refresh_file_tree())

    def _on_file_select(self, event):
        sel = self.file_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._selected_idx = idx
        if 0 <= idx < len(self.files):
            self._display_result(self.files[idx])

    def _compute_quality(self, result: Dict) -> float:
        if not result:
            return 0.0
        score = 0.0
        total_weight = 0.0

        checks = [
            ("selected_nanozyme.name", 0.15),
            ("main_activity.enzyme_like_type", 0.12),
            ("main_activity.substrates", 0.08),
            ("main_activity.kinetics.Km", 0.12),
            ("main_activity.kinetics.Vmax", 0.12),
            ("main_activity.pH_profile.optimal_pH", 0.08),
            ("main_activity.temperature_profile.optimal_temperature", 0.06),
            ("selected_nanozyme.synthesis_method", 0.06),
            ("selected_nanozyme.size", 0.05),
            ("selected_nanozyme.morphology", 0.05),
            ("applications", 0.06),
            ("main_activity.kinetics.kcat", 0.05),
        ]

        for path, weight in checks:
            total_weight += weight
            val = self._get_nested(result, path)
            if val is not None and val != "" and val != []:
                score += weight

        return score / total_weight if total_weight > 0 else 0.0

    @staticmethod
    def _get_nested(d: Dict, path: str):
        keys = path.split(".")
        current = d
        for k in keys:
            if isinstance(current, dict):
                current = current.get(k)
            else:
                return None
            if current is None:
                return None
        return current

    def _display_result(self, fstate: FileState):
        if fstate.result is None:
            self.result_title.config(text=f"{fstate.stem} — 尚无结果")
            self._clear_result_display()
            return

        r = fstate.result
        sel = r.get("selected_nanozyme", {})
        act = r.get("main_activity", {})
        kin = act.get("kinetics", {})
        ph = act.get("pH_profile", {})
        temp = act.get("temperature_profile", {})
        apps = r.get("applications", [])

        self.result_title.config(text=fstate.stem)

        self._set_card("material", "name", sel.get("name", "—"))
        self._set_card("material", "enzyme_type", act.get("enzyme_like_type", "—"))
        self._set_card("material", "morphology", sel.get("morphology", "—"))
        self._set_card("material", "size", sel.get("size", "—"))
        self._set_card("material", "crystal_structure", sel.get("crystal_structure", "—"))
        self._set_card("material", "surface_area", sel.get("surface_area", "—"))
        self._set_card("material", "synthesis_method", sel.get("synthesis_method", "—"))

        self._set_card("kinetics", "Km", self._fmt_num(kin.get("Km")))
        self._set_card("kinetics", "Km_unit", kin.get("Km_unit", "—"))
        self._set_card("kinetics", "Vmax", self._fmt_num(kin.get("Vmax")))
        self._set_card("kinetics", "Vmax_unit", kin.get("Vmax_unit", "—"))
        self._set_card("kinetics", "kcat", self._fmt_num(kin.get("kcat")))
        self._set_card("kinetics", "kcat_unit", kin.get("kcat_unit", "—"))

        self._set_card("conditions", "optimal_pH", self._fmt_num(ph.get("optimal_pH")))
        self._set_card("conditions", "pH_range", ph.get("pH_range", "—"))
        self._set_card("conditions", "optimal_temp", temp.get("optimal_temperature", "—"))
        self._set_card("conditions", "temp_range", temp.get("temperature_range", "—"))
        self._set_card("conditions", "substrates", ", ".join(act.get("substrates", [])) or "—")

        if apps:
            a = apps[0]
            self._set_card("application", "app_type", a.get("type", "—"))
            self._set_card("application", "detection_limit", a.get("detection_limit", "—"))
            self._set_card("application", "linear_range", a.get("linear_range", "—"))
            self._set_card("application", "target", a.get("target", "—"))
        else:
            for k in ("app_type", "detection_limit", "linear_range", "target"):
                self._set_card("application", k, "—")

        quality = self._compute_quality(r)
        fstate.quality_score = quality
        self.quality_ring.update_score(quality)

        diag = r.get("diagnostics", {})
        conf = diag.get("overall_confidence", "—") if diag else "—"
        conf_color = ColorTheme.confidence_color(conf) if conf != "—" else ColorTheme.TEXT_MUTED
        self.conf_label.config(text=f"置信度: {conf}", fg=conf_color)

        status = diag.get("status", "—") if diag else "—"
        self.status_detail_label.config(text=f"状态: {status}")

        warns = diag.get("warnings", []) if diag else []
        self.warn_count_label.config(text=f"警告: {len(warns)}",
                                     fg=ColorTheme.YELLOW if warns else ColorTheme.GREEN)

        self.diag_text.config(state=tk.NORMAL)
        self.diag_text.delete("1.0", tk.END)
        if diag:
            self.diag_text.insert(tk.END, f"整体置信度: {conf}\n", "ok" if conf == "high" else "warn")
            self.diag_text.insert(tk.END, f"状态: {status}\n\n")
            if warns:
                self.diag_text.insert(tk.END, f"警告 ({len(warns)}):\n", "warn")
                for w in warns:
                    tag = "error" if any(kw in w for kw in ["failed", "error", "missing"]) else "warn"
                    self.diag_text.insert(tk.END, f"  • {w}\n", tag)
            else:
                self.diag_text.insert(tk.END, "✓ 无警告\n", "ok")

            coverage = diag.get("field_coverage", {})
            if coverage:
                self.diag_text.insert(tk.END, "\n字段覆盖率:\n")
                for field, status_val in coverage.items():
                    tag = "ok" if status_val == "extracted" else "warn"
                    self.diag_text.insert(tk.END, f"  {field}: {status_val}\n", tag)
        else:
            self.diag_text.insert(tk.END, "无诊断信息\n")
        self.diag_text.config(state=tk.DISABLED)

    def _set_card(self, card_id: str, field_id: str, value):
        if card_id in self._cards and field_id in self._cards[card_id]:
            v = str(value) if value is not None else "—"
            label = self._cards[card_id][field_id]
            label.config(text=v)
            if v == "—":
                label.config(fg=ColorTheme.TEXT_MUTED)
            else:
                label.config(fg=ColorTheme.TEXT_PRIMARY)

    def _clear_result_display(self):
        for card_id, fields in self._cards.items():
            for fid, label in fields.items():
                label.config(text="—", fg=ColorTheme.TEXT_MUTED)
        self.quality_ring.update_score(0.0)
        self.conf_label.config(text="置信度: —", fg=ColorTheme.TEXT_MUTED)
        self.status_detail_label.config(text="状态: —")
        self.warn_count_label.config(text="警告: —", fg=ColorTheme.TEXT_MUTED)
        self.diag_text.config(state=tk.NORMAL)
        self.diag_text.delete("1.0", tk.END)
        self.diag_text.config(state=tk.DISABLED)

    @staticmethod
    def _fmt_num(v):
        if v is None:
            return "—"
        if isinstance(v, float):
            if abs(v) < 0.001 or abs(v) > 1e5:
                return f"{v:.2e}"
            return f"{v:.4g}"
        return str(v)

    def _start_pipeline(self):
        if not self.files:
            messagebox.showwarning("提示", "请先选择PDF文件")
            return
        if self._running:
            return
        self._running = True
        self.stop_event.clear()
        self.run_btn.config(state=tk.DISABLED, bg=ColorTheme.TEXT_MUTED)
        self.stop_btn.config(state=tk.NORMAL, fg=ColorTheme.TEXT_PRIMARY)
        self._start_time = time.time()

        for f in self.files:
            f.phase = "idle"
            f.error = ""
            f.result = None
            f.quality_score = 0.0
        self._refresh_file_tree()
        if self.pipeline_viz:
            self.pipeline_viz.reset()

        threading.Thread(target=self._pipeline_worker, daemon=True).start()

    def _stop_pipeline(self):
        self.stop_event.set()
        self.run_btn.config(state=tk.NORMAL, bg=ColorTheme.ACCENT)
        self.stop_btn.config(state=tk.DISABLED, fg=ColorTheme.TEXT_MUTED)

    def _pipeline_worker(self):
        try:
            self._pipeline_run()
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
        finally:
            self._running = False
            self.root.after(0, lambda: self.run_btn.config(state=tk.NORMAL, bg=ColorTheme.ACCENT))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED, fg=ColorTheme.TEXT_MUTED))
            self._update_analytics()

    def _pipeline_run(self):
        total = len(self.files)
        output_dir = self._get_output_dir()

        for i, fstate in enumerate(self.files):
            if self.stop_event.is_set():
                break

            fstate.start_time = time.time()
            self.root.after(0, lambda idx=i: self._update_progress(idx, total, "解析PDF"))

            try:
                self._update_file_phase(i, "parsing")
                self._set_pipeline_stage(0, "active")
                self._set_pipeline_stage(1, "active")

                pdf_json = self._parse_pdf(fstate.path, output_dir)
                if pdf_json is None:
                    self._update_file_phase(i, "error", "PDF解析失败")
                    self._set_pipeline_stage(1, "error")
                    continue

                if self.stop_event.is_set():
                    break

                self.root.after(0, lambda idx=i: self._update_progress(idx, total, "预处理"))
                self._update_file_phase(i, "preprocessing")
                self._set_pipeline_stage(1, "done")
                self._set_pipeline_stage(2, "active")

                mid_task = self._preprocess(pdf_json, fstate.path, output_dir)
                if mid_task is None:
                    self._update_file_phase(i, "error", "预处理失败")
                    self._set_pipeline_stage(2, "error")
                    continue

                if self.stop_event.is_set():
                    break

                self.root.after(0, lambda idx=i: self._update_progress(idx, total, "提取"))
                self._update_file_phase(i, "extracting")
                self._set_pipeline_stage(2, "done")
                self._set_pipeline_stage(3, "active")
                if self.llm_var.get():
                    self._set_pipeline_stage(4, "active")
                if self.vlm_var.get():
                    self._set_pipeline_stage(5, "active")

                result = self._extract(mid_task, output_dir, fstate.stem)

                self._set_pipeline_stage(3, "done")
                self._set_pipeline_stage(4, "done" if self.llm_var.get() else "idle")
                self._set_pipeline_stage(5, "done" if self.vlm_var.get() else "idle")
                self._set_pipeline_stage(6, "active")

                fstate.end_time = time.time()
                if result is not None:
                    fstate.result = result
                    fstate.quality_score = self._compute_quality(result)
                    self._update_file_phase(i, "done")
                    self._set_pipeline_stage(6, "done")
                    self._set_pipeline_stage(7, "active")
                    self._save_extracted(result, output_dir, fstate.stem)
                    self._set_pipeline_stage(7, "done")
                else:
                    self._update_file_phase(i, "error", "提取失败")
                    self._set_pipeline_stage(6, "error")

            except Exception as e:
                fstate.end_time = time.time()
                self._update_file_phase(i, "error", str(e))
                logger.error(f"[{fstate.stem}] Error: {e}")

            self.root.after(0, lambda idx=i: self._update_progress(idx + 1, total, ""))

        elapsed = time.time() - self._start_time
        self.root.after(0, lambda: self.progress_label.config(
            text=f"完成 ({elapsed:.1f}s)" if not self.stop_event.is_set() else "已停止"
        ))

    def _set_pipeline_stage(self, idx: int, state: str):
        self.root.after(0, lambda: self._set_pipeline_stage_ui(idx, state))

    def _set_pipeline_stage_ui(self, idx: int, state: str):
        if self.pipeline_viz and 0 <= idx < len(self.pipeline_viz.nodes):
            self.pipeline_viz.set_stage(idx, state)

    def _parse_pdf(self, pdf_path: str, output_dir: str) -> Optional[str]:
        try:
            from opendataloader_pdf import convert
            result = convert(pdf_path, output_dir=output_dir)
            if isinstance(result, dict) and result.get("json_path"):
                return result["json_path"]
            if isinstance(result, str) and Path(result).exists():
                return result
            stem = Path(pdf_path).stem
            candidate = Path(output_dir) / f"{stem}.json"
            if candidate.exists():
                return str(candidate)
            return None
        except Exception as e:
            logger.error(f"PDF parse error: {e}")
            return None

    def _preprocess(self, pdf_json: str, pdf_path: str, output_dir: str) -> Optional[str]:
        try:
            from nanozyme_preprocessor_midjson import NanozymePreprocessor
            from config_manager import ConfigManager
            cm = ConfigManager()
            preprocessor = NanozymePreprocessor(cm)
            stem = Path(pdf_path).stem
            images_dir = Path(output_dir) / f"{stem}_images"
            mid_path = preprocessor.process(pdf_json, str(images_dir), output_dir)
            return mid_path if mid_path else None
        except ImportError:
            try:
                from nanozyme_preprocessor_midjson import NanozymePreprocessor
                stem = Path(pdf_path).stem
                images_dir = Path(output_dir) / f"{stem}_images"
                out_dir = Path(output_dir)
                preprocessor = NanozymePreprocessor(
                    json_path=pdf_json,
                    images_root=str(images_dir) if images_dir.exists() else None,
                    output_root=str(out_dir),
                    pdf_stem=stem,
                )
                preprocessor.process()
                mid_path = out_dir / f"{stem}_mid_task.json"
                return str(mid_path) if mid_path.exists() else None
            except Exception as e2:
                logger.error(f"Preprocess error (fallback): {e2}")
                return None
        except Exception as e:
            logger.error(f"Preprocess error: {e}")
            return None

    def _extract(self, mid_task_path: str, output_dir: str, stem: str) -> Optional[Dict]:
        try:
            from extraction_pipeline import ExtractionPipeline
            from config_manager import ConfigManager
            cm = ConfigManager()
            pipeline = ExtractionPipeline(cm)
            loop = asyncio.new_event_loop()
            try:
                enable_llm = self.llm_var.get()
                enable_vlm = self.vlm_var.get()
                result = loop.run_until_complete(
                    pipeline.process_mid_json(mid_task_path, enable_llm=enable_llm, enable_vlm=enable_vlm)
                )
            finally:
                loop.close()
            return result
        except Exception as e:
            logger.error(f"Extract error: {e}")
            try:
                from single_main_nanozyme_extractor import SingleMainNanozymePipeline, SMNConfig
                from config_manager import ConfigManager
                cm = ConfigManager()
                config = SMNConfig(enable_llm=False, enable_vlm=False)
                pipeline = SingleMainNanozymePipeline(client=None, config=config)
                with open(mid_task_path, "r", encoding="utf-8") as f:
                    mid = json.load(f)
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(pipeline.extract(mid))
                finally:
                    loop.close()
                return result
            except Exception as e2:
                logger.error(f"Fallback extract error: {e2}")
                return None

    def _save_extracted(self, result: Dict, output_dir: str, stem: str):
        out_path = Path(output_dir) / f"{stem}_extracted.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"[{stem}] 结果已保存: {out_path}")

    def _get_output_dir(self) -> str:
        if self.files:
            first_dir = str(Path(self.files[0].path).parent)
            out = Path(first_dir) / "extraction_output"
        else:
            out = Path.cwd() / "extraction_output"
        out.mkdir(parents=True, exist_ok=True)
        return str(out)

    def _update_progress(self, current: int, total: int, phase_text: str):
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress["value"] = pct
        if phase_text:
            self.progress_label.config(text=f"{current}/{total} — {phase_text}")
        else:
            self.progress_label.config(text=f"{current}/{total}")

    def _update_analytics(self):
        total = len(self.files)
        done = sum(1 for f in self.files if f.phase == "done")
        errors = sum(1 for f in self.files if f.phase == "error")

        km_count = 0
        vmax_count = 0
        ph_count = 0
        quality_sum = 0.0
        for f in self.files:
            if f.result:
                kin = f.result.get("main_activity", {}).get("kinetics", {})
                ph_prof = f.result.get("main_activity", {}).get("pH_profile", {})
                if kin.get("Km") is not None:
                    km_count += 1
                if kin.get("Vmax") is not None:
                    vmax_count += 1
                if ph_prof.get("optimal_pH") is not None:
                    ph_count += 1
            quality_sum += f.quality_score

        avg_quality = quality_sum / done if done > 0 else 0.0
        km_rate = km_count / done * 100 if done > 0 else 0
        vmax_rate = vmax_count / done * 100 if done > 0 else 0

        self._metric_cards["total"].config(text=str(total))
        self._metric_cards["success"].config(text=str(done), fg=ColorTheme.GREEN if done > 0 else ColorTheme.TEXT_PRIMARY)
        self._metric_cards["failed"].config(text=str(errors), fg=ColorTheme.RED if errors > 0 else ColorTheme.TEXT_PRIMARY)
        self._metric_cards["avg_quality"].config(text=f"{avg_quality:.0%}",
                                                  fg=ColorTheme.quality_gradient(avg_quality))
        self._metric_cards["km_rate"].config(text=f"{km_rate:.0f}%",
                                              fg=ColorTheme.GREEN if km_rate >= 60 else ColorTheme.YELLOW if km_rate >= 40 else ColorTheme.RED)
        self._metric_cards["vmax_rate"].config(text=f"{vmax_rate:.0f}%",
                                                fg=ColorTheme.GREEN if vmax_rate >= 60 else ColorTheme.YELLOW if vmax_rate >= 40 else ColorTheme.RED)

        self._draw_field_chart()

    def _draw_field_chart(self):
        canvas = self.analytics_canvas
        canvas.delete("all")

        done_files = [f for f in self.files if f.result]
        if not done_files:
            canvas.create_text(200, 100, text="暂无数据", fill=ColorTheme.TEXT_MUTED,
                               font=("Microsoft YaHei UI", 12))
            return

        fields = [
            ("材料名称", "selected_nanozyme.name"),
            ("酶类型", "main_activity.enzyme_like_type"),
            ("底物", "main_activity.substrates"),
            ("Km", "main_activity.kinetics.Km"),
            ("Vmax", "main_activity.kinetics.Vmax"),
            ("kcat", "main_activity.kinetics.kcat"),
            ("最适pH", "main_activity.pH_profile.optimal_pH"),
            ("最适温度", "main_activity.temperature_profile.optimal_temperature"),
            ("合成方法", "selected_nanozyme.synthesis_method"),
            ("尺寸", "selected_nanozyme.size"),
            ("应用", "applications"),
        ]

        rates = []
        for label, path in fields:
            count = sum(1 for f in done_files
                        if self._get_nested(f.result, path) not in (None, "", []))
            rate = count / len(done_files) if done_files else 0
            rates.append((label, rate))

        w = canvas.winfo_width() or 600
        h = canvas.winfo_height() or 300
        margin_left = 80
        margin_right = 60
        margin_top = 10
        margin_bottom = 30
        bar_height = max(14, (h - margin_top - margin_bottom) // len(rates) - 6)
        chart_w = w - margin_left - margin_right

        for i, (label, rate) in enumerate(rates):
            y = margin_top + i * (bar_height + 6)

            canvas.create_text(margin_left - 6, y + bar_height // 2, text=label,
                               fill=ColorTheme.TEXT_SECONDARY, font=("Microsoft YaHei UI", 9),
                               anchor=tk.E)

            canvas.create_rectangle(margin_left, y, margin_left + chart_w, y + bar_height,
                                    fill=ColorTheme.BG_DARK, outline="")

            bar_w = chart_w * rate
            if bar_w > 0:
                color = ColorTheme.quality_gradient(rate)
                canvas.create_rectangle(margin_left, y, margin_left + bar_w, y + bar_height,
                                        fill=color, outline="")

            canvas.create_text(margin_left + chart_w + 6, y + bar_height // 2,
                               text=f"{rate:.0%}", fill=ColorTheme.TEXT_PRIMARY,
                               font=("Microsoft YaHei UI", 9, "bold"), anchor=tk.W)

    def _save_result(self):
        if self._selected_idx is None or self._selected_idx >= len(self.files):
            messagebox.showinfo("提示", "请先选择一个文件")
            return
        fstate = self.files[self._selected_idx]
        if fstate.result is None:
            messagebox.showinfo("提示", "该文件尚无提取结果")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"{fstate.stem}_extracted.json"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(fstate.result, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("成功", f"已保存到 {path}")

    def _open_result_dir(self):
        output_dir = self._get_output_dir()
        os.startfile(output_dir)

    def append_log(self, level: str, msg: str):
        self.log_text.config(state=tk.NORMAL)
        tag = level if level in ("INFO", "WARNING", "ERROR", "SUCCESS") else "INFO"
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)


class _DashboardLogHandler(logging.Handler):
    def __init__(self, app: NanozymeDashboard):
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            level = record.levelname
            if level == "WARNING":
                level = "WARNING"
            elif level == "ERROR":
                level = "ERROR"
            elif "✓" in msg or "成功" in msg:
                level = "SUCCESS"
            else:
                level = "INFO"
            self.app.root.after(0, lambda: self.app.append_log(level, msg))
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = NanozymeDashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
