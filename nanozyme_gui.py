import sys
import os
import io
import contextlib
import re
import json
import subprocess
import threading
import time
import warnings
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
import logging
import collections

try:
    import orjson
    _USE_ORJSON = True
except ImportError:
    _USE_ORJSON = False

from dependencies import is_available, get_module

CONFIG_MANAGER_AVAILABLE = is_available("config_manager")
if CONFIG_MANAGER_AVAILABLE:
    from config_manager import ConfigManager

LOGGING_SETUP_AVAILABLE = is_available("logging_setup")
if LOGGING_SETUP_AVAILABLE:
    from logging_setup import setup_logging, GUILogHandler
else:
    GUILogHandler = None

PREPROCESSOR_AVAILABLE = is_available("nanozyme_preprocessor_midjson")
if PREPROCESSOR_AVAILABLE:
    from nanozyme_preprocessor_midjson import NanozymePreprocessor

_YEAR_HASH_RE = re.compile(r'(\d{4})')
_MAX_LOG_QUEUE_SIZE = 1000


def _fast_json_loads(data):
    return orjson.loads(data) if _USE_ORJSON else json.loads(data)


def _fast_json_dumps(obj, indent=False):
    opts = orjson.OPT_INDENT_2 if indent else 0
    return orjson.dumps(obj, option=opts).decode('utf-8') if _USE_ORJSON else json.dumps(obj, indent=indent, ensure_ascii=False)


def _resolve_pdf_assets(pdf_path: Path, output_dir: Optional[str]) -> Tuple[Path, Path]:
    base = Path(output_dir) if output_dir else pdf_path.parent
    json_path = base / (pdf_path.stem + ".json")
    images_dir = base / (pdf_path.stem + "_images")
    return json_path, images_dir


warnings.filterwarnings(
    "ignore",
    message=r".*pin_memory.*accelerator.*",
    category=UserWarning,
)


@dataclass
class FileProcessReport:
    pdf_name: str
    pdf_path: str
    json_path: str
    images_dir: str
    server_convert_ok: bool = False
    response_parse_ok: bool = False
    artifact_written_ok: bool = False
    ocr_fallback_used: bool = False
    parse_status: str = "FAILED"
    protocol_error: bool = False
    preprocess_status: str = "FAILED"
    mid_task_written: bool = False
    mid_task_path: str = ""
    final_status: str = "FAILED"
    error_message: str = ""
    parse_seconds: float = 0.0
    ocr_seconds: float = 0.0
    preprocess_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class NanozymeGUI:
    DEFAULT_PROFILE = {
        "format": "json",
        "use_struct_tree": True,
        "reading_order": "xycut",
        "image_output": "external",
        "image_format": "png",
        "table_method": "default",
        "threads": "2",
    }

    HYBRID_PROFILE = {
        "format": "json",
        "use_struct_tree": True,
        "reading_order": "xycut",
        "image_output": "external",
        "image_format": "png",
        "hybrid": "docling-fast",
        "hybrid_mode": "auto",
        "hybrid_url": "http://localhost:5002",
        "hybrid_timeout": "120000",
        "hybrid_fallback": True,
        "table_method": "default",
        "threads": "2",
    }

    def __init__(self, root):
        self.root = root
        self.root.title("纳米酶文献提取系统")
        self.root.geometry("900x750")
        self.root.resizable(True, True)

        self.server_ready = False

        self.input_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.recursive = tk.BooleanVar(value=False)
        self.mid_json_output_dir = tk.StringVar()
        self.extracted_json_output_dir = tk.StringVar()
        self._extraction_mode = "single_main_nanozyme"

        self.mid_json_path = None
        self.extracted_json_path = None
        self.extracted_json_paths: List[str] = []
        self.stop_event = threading.Event()
        self.extract_stop_event = threading.Event()
        self.file_reports: List[FileProcessReport] = []
        self._benign_warning_cache: set[str] = set()

        self.llm_config = None
        self.vlm_config = None

        self.create_widgets()
        self.log_queue = collections.deque(maxlen=_MAX_LOG_QUEUE_SIZE)
        self.update_log()
        self.load_model_config()
        self.setup_logging_handler()
        # 初始化时直接标记服务器为就绪（使用 Python API 无需外部服务器）
        self.server_ready = True
        self.server_status.config(text="● 就绪", foreground="green")
        self.set_phase_status("server", "ok")

    def create_widgets(self):
        style = ttk.Style()
        style.configure("Status.TLabel", font=('Arial', 9))
        style.configure("Header.TLabel", font=('Arial', 10, 'bold'))
        style.configure("Phase.TLabel", font=('Arial', 9), padding=3)
        style.configure("Section.TFrame", background="#f5f5f5", relief=tk.RIDGE)

        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill="both", expand=True, padx=8, pady=4)

        # ── 顶部：系统状态仪表板 ──────────────────────────────────────────────
        dashboard = ttk.LabelFrame(main_frame, text="系统状态", padding=6)
        dashboard.pack(fill="x", pady=(0, 4))

        phases_frame = ttk.Frame(dashboard)
        phases_frame.pack(fill="x")

        self.phase_indicators = {}
        phases = [
            ("server", "PDF 服务器"),
            ("llm", "文本大模型"),
            ("vlm", "视觉大模型"),
            ("parse", "PDF 解析"),
            ("preprocess", "预处理"),
            ("extract", "智能提取"),
        ]
        for i, (key, label) in enumerate(phases):
            f = ttk.Frame(phases_frame)
            f.pack(side="left", expand=True, fill="x", padx=2)
            indicator = tk.Label(f, text="●", font=('Arial', 14), fg="#cccccc")
            indicator.pack()
            lbl = ttk.Label(f, text=label, style="Phase.TLabel", anchor="center")
            lbl.pack()
            self.phase_indicators[key] = indicator

        # ── 主内容区：单窗口布局 ──────────────────────────────────────────────
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill="both", expand=True, pady=4)

        # 左面板：输入与处理设置
        left_panel = ttk.Frame(content_frame, width=400)
        left_panel.pack(side="left", fill="y", padx=(0, 4))
        left_panel.pack_propagate(False)

        # 输入设置
        input_section = ttk.LabelFrame(left_panel, text="📁 输入设置", padding=8)
        input_section.pack(fill="x", pady=(0, 4))

        ttk.Label(input_section, text="PDF 文件或文件夹:").pack(anchor="w", pady=(0, 2))
        ttk.Entry(input_section, textvariable=self.input_path, width=45).pack(fill="x", pady=(0, 4))
        input_btn_frame = ttk.Frame(input_section)
        input_btn_frame.pack(fill="x")
        ttk.Button(input_btn_frame, text="选择文件", command=self.select_files, width=12).pack(side="left")
        ttk.Button(input_btn_frame, text="选择文件夹", command=self.select_folder, width=12).pack(side="left", padx=4)
        ttk.Checkbutton(input_section, text="递归处理子文件夹", variable=self.recursive).pack(anchor="w", pady=2)

        ttk.Label(input_section, text="输出目录:").pack(anchor="w", pady=(4, 2))
        ttk.Entry(input_section, textvariable=self.output_dir, width=45).pack(fill="x", pady=(0, 4))
        ttk.Button(input_section, text="选择目录", command=self.select_output_dir).pack(anchor="w")

        # PDF 解析服务器
        server_section = ttk.LabelFrame(left_panel, text="🔌 PDF 解析服务器", padding=8)
        server_section.pack(fill="x", pady=4)

        server_btn_frame = ttk.Frame(server_section)
        server_btn_frame.pack(fill="x")
        ttk.Button(server_btn_frame, text="启动服务器", command=self.start_server, width=12).pack(side="left")
        ttk.Button(server_btn_frame, text="停止服务器", command=self.stop_server, width=12).pack(side="left", padx=4)
        self.server_status = ttk.Label(server_btn_frame, text="● 未启动", foreground="red", style="Status.TLabel")
        self.server_status.pack(side="left", padx=8)

        ttk.Label(server_section, text="docling-fast | auto OCR fallback", foreground="gray", font=('Arial', 8)).pack(anchor="w", pady=(4, 0))

        # 大模型状态
        model_section = ttk.LabelFrame(left_panel, text="🤖 大模型状态", padding=8)
        model_section.pack(fill="x", pady=4)

        llm_row = ttk.Frame(model_section)
        llm_row.pack(fill="x", pady=2)
        ttk.Label(llm_row, text="LLM:", font=('Arial', 9, 'bold'), width=6).pack(side="left")
        self.text_llm_label = ttk.Label(llm_row, text="加载中...", foreground="gray", wraplength=280)
        self.text_llm_label.pack(side="left", padx=2, fill="x")

        vlm_row = ttk.Frame(model_section)
        vlm_row.pack(fill="x", pady=2)
        ttk.Label(vlm_row, text="VLM:", font=('Arial', 9, 'bold'), width=6).pack(side="left")
        self.vlm_label = ttk.Label(vlm_row, text="加载中...", foreground="gray", wraplength=280)
        self.vlm_label.pack(side="left", padx=2, fill="x")

        model_btn_row = ttk.Frame(model_section)
        model_btn_row.pack(fill="x", pady=4)
        ttk.Button(model_btn_row, text="测试 API", command=self.test_model_connection).pack(side="left")
        ttk.Button(model_btn_row, text="刷新配置", command=self.load_model_config).pack(side="left", padx=4)

        # 提取设置
        extract_section = ttk.LabelFrame(left_panel, text="⚙️ 提取设置", padding=8)
        extract_section.pack(fill="x", pady=4)

        ttk.Label(extract_section, text="提取模式: 单主纳米酶").pack(anchor="w", pady=(0, 4))

        ttk.Label(extract_section, text="中间JSON目录:").pack(anchor="w", pady=2)
        ttk.Entry(extract_section, textvariable=self.mid_json_output_dir, width=35).pack(fill="x", pady=(0, 2))
        ttk.Button(extract_section, text="选择", command=self.select_mid_json_output).pack(anchor="w", pady=(0, 4))

        ttk.Label(extract_section, text="提取结果目录:").pack(anchor="w", pady=2)
        ttk.Entry(extract_section, textvariable=self.extracted_json_output_dir, width=35).pack(fill="x", pady=(0, 2))
        ttk.Button(extract_section, text="选择", command=self.select_extracted_json_output).pack(anchor="w", pady=(0, 4))

        self.force_reextract_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(extract_section, text="强制重新提取", variable=self.force_reextract_var).pack(anchor="w")

        # 右面板：控制按钮与状态
        right_panel = ttk.Frame(content_frame)
        right_panel.pack(side="right", fill="both", expand=True)

        # 控制按钮区
        control_section = ttk.LabelFrame(right_panel, text="▶ 流程控制", padding=8)
        control_section.pack(fill="x", pady=(0, 4))

        # 预处理按钮
        preprocess_frame = ttk.Frame(control_section)
        preprocess_frame.pack(fill="x", pady=4)
        self.start_btn = ttk.Button(preprocess_frame, text="📄 开始预处理", command=self.start_conversion, width=20)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(preprocess_frame, text="⏹ 停止", command=self.stop_conversion, state=tk.DISABLED, width=10)
        self.stop_btn.pack(side="left", padx=4)

        self.preprocess_progress = ttk.Progressbar(control_section, mode='determinate', maximum=100)
        self.preprocess_progress.pack(fill="x", pady=4)
        self.preprocess_status = ttk.Label(control_section, text="预处理状态: 等待输入", foreground="gray")
        self.preprocess_status.pack(anchor="w")

        # 提取按钮
        extract_frame = ttk.Frame(control_section)
        extract_frame.pack(fill="x", pady=4)
        self.extract_btn = ttk.Button(extract_frame, text="🧠 启动智能提取", command=self.start_extraction, state=tk.DISABLED, width=20)
        self.extract_btn.pack(side="left")
        self.stop_extract_btn = ttk.Button(extract_frame, text="⏹ 停止", command=self.stop_extraction, state=tk.DISABLED, width=10)
        self.stop_extract_btn.pack(side="left", padx=4)

        self.extract_progress = ttk.Progressbar(control_section, mode='determinate', maximum=100)
        self.extract_progress.pack(fill="x", pady=4)
        self.extract_status = ttk.Label(control_section, text="提取状态: 等待预处理完成", foreground="gray")
        self.extract_status.pack(anchor="w")

        # 结果查看按钮
        result_frame = ttk.Frame(control_section)
        result_frame.pack(fill="x", pady=4)
        self.view_result_btn = ttk.Button(result_frame, text="📋 查看结果", command=self.view_result, state=tk.DISABLED, width=20)
        self.view_result_btn.pack(side="left")

        # 运行日志区
        log_section = ttk.LabelFrame(right_panel, text="📝 运行日志", padding=8)
        log_section.pack(fill="both", expand=True, pady=4)

        log_btn_frame = ttk.Frame(log_section)
        log_btn_frame.pack(fill="x")
        ttk.Button(log_btn_frame, text="清除日志", command=lambda: self.log_text.delete('1.0', tk.END)).pack(side="right")

        self.log_text = scrolledtext.ScrolledText(log_section, height=20, wrap=tk.WORD, font=('Consolas', 9))
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("error", foreground="red")
        self.log_text.tag_config("warn", foreground="#cc6600")
        self.log_text.tag_config("info", foreground="#0066cc")
        self.log_text.tag_config("success", foreground="#009933")

        # ── 底部状态栏 ────────────────────────────────────────────────────────
        status_bar = ttk.Frame(main_frame)
        status_bar.pack(fill="x", pady=(2, 0))
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_bar, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W,
                  style="Status.TLabel").pack(side="left", fill="x", expand=True, padx=2)
        self.file_count_var = tk.StringVar(value="")
        ttk.Label(status_bar, textvariable=self.file_count_var, relief=tk.SUNKEN, anchor=tk.E,
                  style="Status.TLabel", width=25).pack(side="right", padx=2)

    def set_phase_status(self, phase: str, status: str):
        colors = {
            "idle": "#cccccc",
            "running": "#ffaa00",
            "ok": "#00cc44",
            "error": "#ff3333",
            "disabled": "#999999",
        }
        color = colors.get(status, "#cccccc")
        if phase in self.phase_indicators:
            self.phase_indicators[phase].config(fg=color)

    def load_model_config(self):
        try:
            if CONFIG_MANAGER_AVAILABLE:
                try:
                    ConfigManager.reset_instance()
                    cfg = ConfigManager.get_instance()
                    self.llm_config = cfg.llm.to_dict() if cfg.llm else {}
                    self.vlm_config = cfg.vlm.to_dict() if cfg.vlm else {}

                    llm_model = cfg.llm.model if cfg.llm else '未配置'
                    llm_url = cfg.llm.base_url if cfg.llm else ''
                    llm_api_set = '✓' if (cfg.llm and cfg.llm.validate()) else '✗'

                    vlm_model = cfg.vlm.model if cfg.vlm else '未配置'
                    vlm_url = cfg.vlm.base_url if cfg.vlm else ''
                    vlm_api_set = '✓' if (cfg.vlm and cfg.vlm.validate()) else '✗'

                    self.log("[配置] 通过 ConfigManager 加载大模型配置")
                except Exception as e:
                    self.log(f"[配置] ConfigManager 加载失败，回退到手动读取: {e}")
                    self._load_model_config_fallback()
                    return
            else:
                self._load_model_config_fallback()
                return

            self.text_llm_label.config(
                text=f"模型: {llm_model} | API: {llm_url} | 密钥: {llm_api_set}",
                foreground="green" if llm_api_set == '✓' else "red"
            )
            self.vlm_label.config(
                text=f"模型: {vlm_model} | API: {vlm_url} | 密钥: {vlm_api_set}",
                foreground="green" if vlm_api_set == '✓' else "red"
            )

            self.log("[配置] 大模型配置已加载,请点击'测试 API'验证连通性")

        except Exception as e:
            self.text_llm_label.config(text=f"加载失败: {str(e)}", foreground="red")
            self.vlm_label.config(text=f"加载失败: {str(e)}", foreground="red")
            self.log(f"[配置] 加载大模型配置失败: {e}")

    def _load_model_config_fallback(self):
        config_path = Path("config.yaml")
        if not config_path.exists():
            self.text_llm_label.config(text="配置文件不存在", foreground="red")
            self.vlm_label.config(text="配置文件不存在", foreground="red")
            return

        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        providers = config.get('providers', {})
        self.llm_config = providers.get('llm', config.get('text_llm', {}))
        self.vlm_config = providers.get('vlm', config.get('vision_vlm', {}))

        llm_model = self.llm_config.get('model', '未配置')
        llm_url = self.llm_config.get('base_url', '')
        llm_api_set = '✓' if self.llm_config.get('api_key') and self.llm_config['api_key'] not in ['your-deepseek-api-key', 'your-key', ''] else '✗'

        vlm_model = self.vlm_config.get('model', '未配置')
        vlm_url = self.vlm_config.get('base_url', '')
        vlm_api_set = '✓' if self.vlm_config.get('api_key') and self.vlm_config['api_key'] not in ['your-openai-api-key', 'your-key', ''] else '✗'

        self.text_llm_label.config(
            text=f"模型: {llm_model} | API: {llm_url} | 密钥: {llm_api_set}",
            foreground="green" if llm_api_set == '✓' else "red"
        )
        self.vlm_label.config(
            text=f"模型: {vlm_model} | API: {vlm_url} | 密钥: {vlm_api_set}",
            foreground="green" if vlm_api_set == '✓' else "red"
        )
        self.log("[配置] 大模型配置已加载(手动读取),请点击'测试 API'验证连通性")

    def test_model_connection(self):
        if not self.llm_config and not self.vlm_config:
            messagebox.showwarning("提示", "请先加载配置")
            return
        self.log("[连接测试] 开始测试大模型连通性...")
        self.text_llm_label.config(text="测试中...", foreground="orange")
        self.vlm_label.config(text="测试中...", foreground="orange")
        threading.Thread(target=self._test_model_worker, daemon=True).start()

    def _test_model_worker(self):
        try:
            import asyncio
            from api_client import APIClient

            async def test_both():
                results = {'text': None, 'vision': None}
                try:
                    async with APIClient() as client:
                        self.log("[连接测试] 测试文本 LLM...")
                        results['text'] = await client.test_connection('text')
                        self.log("[连接测试] 测试视觉 VLM...")
                        results['vision'] = await client.test_connection('vision')
                except Exception as e:
                    self.log(f"[连接测试] 测试失败: {e}")
                return results

            results = asyncio.run(test_both())

            text_result = results.get('text')
            vision_result = results.get('vision')

            if text_result:
                llm_model = self.llm_config.get('model', '') if self.llm_config else ''
                if text_result.get('success'):
                    msg = f"✓ {llm_model}"
                    self.root.after(0, lambda m=msg: self.text_llm_label.config(text=m, foreground="green"))
                    self.log(f"[连接测试] 文本 LLM: {text_result['message']}")
                    self.root.after(0, lambda: self.set_phase_status("llm", "ok"))
                else:
                    msg = f"✗ {text_result['message']}"
                    self.root.after(0, lambda m=msg: self.text_llm_label.config(text=m, foreground="red"))
                    self.log(f"[连接测试] 文本 LLM 失败: {text_result['message']}")
                    self.root.after(0, lambda: self.set_phase_status("llm", "error"))

            if vision_result:
                vlm_model = self.vlm_config.get('model', '') if self.vlm_config else ''
                if vision_result.get('success'):
                    msg = f"✓ {vlm_model}"
                    self.root.after(0, lambda m=msg: self.vlm_label.config(text=m, foreground="green"))
                    self.log(f"[连接测试] 视觉 VLM: {vision_result['message']}")
                    self.root.after(0, lambda: self.set_phase_status("vlm", "ok"))
                else:
                    msg = f"✗ {vision_result['message']}"
                    self.root.after(0, lambda m=msg: self.vlm_label.config(text=m, foreground="red"))
                    self.log(f"[连接测试] 视觉 VLM 失败: {vision_result['message']}")
                    self.root.after(0, lambda: self.set_phase_status("vlm", "error"))

        except Exception as e:
            self.log(f"[连接测试] 异常: {e}")
            import traceback
            self.log(traceback.format_exc())
            self.root.after(0, lambda: self.text_llm_label.config(text=f"✗ 测试异常", foreground="red"))
            self.root.after(0, lambda: self.vlm_label.config(text=f"✗ 测试异常", foreground="red"))

    def setup_logging_handler(self):
        class _PinMemoryFilter(logging.Filter):
            def filter(self, record):
                if record.levelno == logging.WARNING and 'pin_memory' in record.getMessage():
                    return False
                return True
        logging.getLogger().addFilter(_PinMemoryFilter())

        if LOGGING_SETUP_AVAILABLE:
            try:
                setup_logging(level=logging.INFO, log_file="ocr_gui.log", use_colors=False)
                self.log("[系统] 统一日志模块已初始化（含文件日志: ocr_gui.log）")
            except Exception as e:
                self.log(f"[系统] 统一日志初始化失败，使用默认配置: {e}")

        if LOGGING_SETUP_AVAILABLE and GUILogHandler is not None:
            gui_handler = GUILogHandler(gui_callback=self.log)
            gui_handler.setLevel(logging.INFO)
            gui_handler.setFormatter(logging.Formatter('%(message)s'))
            root_logger = logging.getLogger()
            root_logger.addHandler(gui_handler)
            root_logger.setLevel(logging.INFO)
        else:
            handler = logging.StreamHandler()
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter('%(message)s'))
            logging.getLogger().addHandler(handler)

        for name in ('single_main_nanozyme_extractor', 'nanozyme_preprocessor_midjson',
                     'extraction_pipeline', 'llm_extractor', 'vlm_extractor',
                     'api_client', 'RuleExtractor', 'TableProcessor'):
            logging.getLogger(name).setLevel(logging.INFO)

        self.log("[系统] 日志系统已初始化")

    def log(self, msg):
        tag = None
        if msg.startswith("ERROR") or "✗" in msg:
            tag = "error"
        elif msg.startswith("WARNING") or msg.startswith("WARN") or "⚠" in msg:
            tag = "warn"
        elif "✓" in msg or "成功" in msg:
            tag = "success"
        self.log_queue.append((msg + "\n", tag))

    def update_log(self):
        if self.log_queue:
            batch = []
            while self.log_queue:
                batch.append(self.log_queue.popleft())
            if batch:
                combined = "".join(text for text, _ in batch)
                first_tag = batch[0][1] if batch else None
                all_same_tag = all(tag == first_tag for _, tag in batch)
                if all_same_tag and first_tag:
                    self.log_text.insert(tk.END, combined, first_tag)
                else:
                    for text, tag in batch:
                        self.log_text.insert(tk.END, text, tag if tag else ())
                self.log_text.see(tk.END)
                line_count = int(self.log_text.index('end-1c').split('.')[0])
                if line_count > 5000:
                    self.log_text.delete('1.0', f'{line_count - 3000}.0')
        self.root.after(150, self.update_log)

    def select_files(self):
        files = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        if not files:
            return
        existing = self.input_path.get().strip()
        existing_paths = [p.strip() for p in existing.split(";") if p.strip()] if existing else []
        all_paths = existing_paths + [str(f) for f in files if str(f) not in existing_paths]
        self.input_path.set(";".join(all_paths))

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.input_path.set(folder)

    def select_output_dir(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir.set(folder)

    def select_mid_json_output(self):
        folder = filedialog.askdirectory(title="选择中间 JSON 输出目录")
        if folder:
            self.mid_json_output_dir.set(folder)
            self.log(f"[配置] 中间 JSON 输出目录: {folder}")

    def select_extracted_json_output(self):
        folder = filedialog.askdirectory(title="选择提取结果输出目录")
        if folder:
            self.extracted_json_output_dir.set(folder)
            self.log(f"[配置] 提取结果输出目录: {folder}")

    def start_server(self):
        self.log("[提示] 无需启动外部服务器，直接使用 Python API 处理 PDF")
        self.server_ready = True
        self.server_status.config(text="● 就绪", foreground="green")
        self.set_phase_status("server", "ok")

    def stop_server(self):
        self.log("[提示] 无外部服务器需要停止")
        self.server_ready = True
        self.server_status.config(text="● 就绪", foreground="green")

    def _needs_ocr_fallback(self, json_path: str) -> Tuple[bool, str]:
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return False, "json_read_failed"

        kids = data.get('kids', [])
        if not kids:
            kids = data.get('text', [])
            if not kids:
                return True, "empty_kids"

        text_blocks = 0
        image_blocks = 0
        total_text_chars = 0
        pages_with_text = set()

        def count_recursive(items, page_num=None):
            nonlocal text_blocks, image_blocks, total_text_chars, pages_with_text
            for item in items:
                if not isinstance(item, dict):
                    continue
                p = item.get('page number', page_num)
                itype = item.get('type', '')
                content = item.get('content', '')
                nested = item.get('kids', [])
                if isinstance(nested, list) and nested:
                    count_recursive(nested, p)
                    continue
                rows = item.get('rows', [])
                if isinstance(rows, list) and rows:
                    for row in rows:
                        if isinstance(row, dict):
                            cells = row.get('cells', [])
                            if isinstance(cells, list):
                                for cell in cells:
                                    if isinstance(cell, dict):
                                        ccontent = cell.get('content', '')
                                        if isinstance(ccontent, str) and ccontent.strip():
                                            total_text_chars += len(ccontent)
                if itype in ('paragraph', 'heading', 'list'):
                    text_blocks += 1
                    if isinstance(content, str) and content.strip():
                        total_text_chars += len(content)
                        if p is not None:
                            pages_with_text.add(p)
                elif itype in ('image', 'picture'):
                    image_blocks += 1

        count_recursive(kids)

        total_blocks = text_blocks + image_blocks
        if total_blocks == 0:
            return True, "empty_document"

        reasons = []
        if text_blocks < 8:
            reasons.append(f"text_blocks_too_few({text_blocks})")
        if total_text_chars < 800:
            reasons.append(f"text_chars_too_few({total_text_chars})")
        if total_text_chars < 1200 and text_blocks < 15:
            reasons.append(f"weak_text_layer({total_text_chars}chars/{text_blocks}blocks)")
        if image_blocks > 0 and image_blocks / max(total_blocks, 1) > 0.6:
            reasons.append(f"image_dominated({image_blocks}/{total_blocks})")
        max_pages = data.get('number of pages', 1)
        if max_pages > 1 and len(pages_with_text) <= 1:
            reasons.append(f"few_text_pages({len(pages_with_text)}/{max_pages})")

        if reasons:
            return True, ";".join(reasons)
        return False, ""

    def _ensure_server(self, mode: str = "standard"):
        if not self.server_ready:
            self.server_ready = True
            self.server_status.config(text="● 就绪", foreground="green")
            self.set_phase_status("server", "ok")
            self.log("[提示] 已就绪，使用 Python API 处理 PDF")

    def start_conversion(self):
        input_path = self.input_path.get().strip()
        if not input_path:
            messagebox.showerror("错误", "请选择 PDF 文件或文件夹")
            return
        self._do_conversion()

    def _do_conversion(self):
        self.start_btn.config(state=tk.DISABLED)
        self.extract_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.root.after(0, lambda: self.preprocess_progress.configure(value=0))
        self.stop_event.clear()
        self.convert_thread = threading.Thread(target=self.convert_worker, daemon=True)
        self.convert_thread.start()

    def convert_worker(self):
        try:
            input_path = self.input_path.get().strip()
            paths = [p.strip() for p in input_path.split(";") if p.strip()]
            output_dir = self.output_dir.get().strip() or None

            self.log(f"[解析] 固定 Profile: {self.DEFAULT_PROFILE}")
            self.log(f"[解析] 输入路径数: {len(paths)}")

            all_pdf_paths = []
            for p in paths:
                if os.path.isdir(p):
                    if self.recursive.get():
                        for root, dirs, files in os.walk(p):
                            for f in sorted(files):
                                if f.lower().endswith('.pdf'):
                                    all_pdf_paths.append(os.path.join(root, f))
                    else:
                        for f in sorted(os.listdir(p)):
                            if f.lower().endswith('.pdf'):
                                all_pdf_paths.append(os.path.join(p, f))
                elif p.lower().endswith('.pdf'):
                    all_pdf_paths.append(p)

            if not all_pdf_paths:
                self.log("错误: 未找到任何 PDF 文件")
                return

            self.log(f"[解析] 实际待处理 PDF 数: {len(all_pdf_paths)}")
            self.root.after(0, lambda: self.preprocess_progress.configure(value=5))

            self.file_reports = []
            reports: Dict[str, FileProcessReport] = {}
            for pdf_path in all_pdf_paths:
                stem = Path(pdf_path).stem
                base = Path(output_dir) if output_dir else Path(pdf_path).parent
                r = FileProcessReport(
                    pdf_name=stem,
                    pdf_path=str(pdf_path),
                    json_path=str(base / (stem + ".json")),
                    images_dir=str(base / (stem + "_images")),
                )
                reports[pdf_path] = r

            capture_buf = io.StringIO()
            with contextlib.redirect_stdout(capture_buf):
                try:
                    kwargs = dict(self.DEFAULT_PROFILE)
                    kwargs["input_path"] = all_pdf_paths
                    if output_dir:
                        kwargs["output_dir"] = output_dir
                    self.log(f"[解析] [Python API] 本地模式 convert (threads={kwargs.get('threads', '1')})")
                    import opendataloader_pdf
                    opendataloader_pdf.convert(**kwargs)
                    self.log(f"[解析] [Python API] ✓ 批量解析完成 ({len(all_pdf_paths)} 个 PDF)")
                    for pdf_path in all_pdf_paths:
                        r = reports[pdf_path]
                        r.server_convert_ok = True
                        r.response_parse_ok = True

                except UnicodeDecodeError as ude:
                    self.log(f"[解析] [Python API] UnicodeDecodeError: {ude}")
                    self.log("[解析] [Python API] 检查哪些文件已落盘...")
                    missing = []
                    for pdf_path in all_pdf_paths:
                        r = reports[pdf_path]
                        r.server_convert_ok = True
                        r.response_parse_ok = False
                        r.protocol_error = True
                        if Path(r.json_path).exists():
                            r.artifact_written_ok = True
                            r.parse_status = "SUCCESS_WITH_PROTOCOL_ERROR"
                            self.log(f"[解析] ⚠ {r.pdf_name}: parse=SUCCESS_WITH_PROTOCOL_ERROR")
                        else:
                            r.artifact_written_ok = False
                            r.parse_status = "FAILED"
                            missing.append(pdf_path)
                            self.log(f"[解析] ✗ {r.pdf_name}: parse=FAILED")

                    if missing:
                        self.log(f"[解析] [CLI Fallback] 对 {len(missing)} 个缺失文件启动 CLI 补跑...")
                        for mpath in missing:
                            r = reports[mpath]
                            stem = Path(mpath).stem
                            base = Path(output_dir) if output_dir else Path(mpath).parent
                            out_json = base / (stem + ".json")
                            cmd = ["opendataloader-pdf", str(mpath), "--format=json",
                                   "--use-struct-tree", "--reading-order=xycut",
                                   "--image-output=external", "--image-format=png",
                                   f"--output-dir={str(base)}"]
                            self.log(f"[解析] [CLI Fallback] 补跑: {stem}")
                            try:
                                result = subprocess.run(cmd, capture_output=True, text=True,
                                                        encoding='utf-8', errors='replace', timeout=600)
                                if out_json.exists():
                                    r.artifact_written_ok = True
                                    r.parse_status = "SUCCESS_WITH_PROTOCOL_ERROR"
                                    r.ocr_fallback_used = True
                                    self.log(f"[解析] [CLI Fallback] ✓ {stem}")
                                else:
                                    self.log(f"[解析] [CLI Fallback] ✗ {stem}")
                            except subprocess.TimeoutExpired:
                                self.log(f"[解析] [CLI Fallback] ✗ 超时: {stem}")
                            except Exception as e:
                                self.log(f"[解析] [CLI Fallback] ✗ 异常: {stem}: {e}")

                except Exception as e:
                    self.log(f"[解析] [Python API] 异常: {e}")
                    for pdf_path in all_pdf_paths:
                        r = reports[pdf_path]
                        if r.parse_status == "FAILED":
                            r.error_message = str(e)

            for line in capture_buf.getvalue().strip().splitlines():
                self.log(f"[转换] {line}")

            if self.stop_event.is_set():
                self.log("用户请求停止，跳过剩余文件...")
                return
            self.root.after(0, lambda: self.preprocess_progress.configure(value=40))

            for pdf_path in all_pdf_paths:
                r = reports[pdf_path]
                if r.parse_status == "FAILED" and Path(r.json_path).exists():
                    r.parse_status = "SUCCESS"
                    r.artifact_written_ok = True

            needs_ocr_list = []
            standard_ok_list = []
            for pdf_path in all_pdf_paths:
                r = reports[pdf_path]
                if Path(r.json_path).exists():
                    needs_ocr, reason = self._needs_ocr_fallback(r.json_path)
                    if needs_ocr:
                        needs_ocr_list.append((pdf_path, reason))
                    else:
                        standard_ok_list.append(pdf_path)

            self.log(f"[OCR Fallback] 标准解析: {len(standard_ok_list)} 个文件正常")
            if needs_ocr_list:
                for pdf_path, reason in needs_ocr_list:
                    self.log(f"[OCR Fallback] {os.path.basename(pdf_path)} -> reason={reason}")
                self.log(f"[OCR Fallback] 仅对 {len(needs_ocr_list)} 个文件重跑 OCR")

            if needs_ocr_list and not self.stop_event.is_set():
                self._ensure_server(mode="ocr")

                hybrid_available = False
                try:
                    import subprocess
                    result = subprocess.run(
                        ["opendataloader-pdf-hybrid", "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    hybrid_available = True
                except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                    pass

                if hybrid_available:
                    self.log("[OCR Fallback] 检测到 hybrid 后端，使用 docling-fast 模式重跑")
                    ocr_profile = self.HYBRID_PROFILE
                else:
                    self.log("[OCR Fallback] hybrid 后端不可用，使用本地模式重跑（含 hybrid_fallback）")
                    ocr_profile = dict(self.DEFAULT_PROFILE)
                    ocr_profile["hybrid"] = "docling-fast"
                    ocr_profile["hybrid_mode"] = "auto"
                    ocr_profile["hybrid_timeout"] = "120000"
                    ocr_profile["hybrid_fallback"] = True

                def _ocr_one(item):
                    pdf_path, _reason = item
                    r = reports[pdf_path]
                    stem = Path(pdf_path).stem
                    base = Path(output_dir) if output_dir else Path(pdf_path).parent
                    out_json = base / (stem + ".json")
                    ocr_buf = io.StringIO()
                    with contextlib.redirect_stdout(ocr_buf):
                        try:
                            ocr_kwargs = dict(ocr_profile)
                            ocr_kwargs["input_path"] = [str(pdf_path)]
                            ocr_kwargs["output_dir"] = str(base)
                            import opendataloader_pdf
                            opendataloader_pdf.convert(**ocr_kwargs)
                        except UnicodeDecodeError:
                            pass
                        except Exception as e:
                            self.log(f"[OCR Fallback] {stem} 重跑异常: {e}")
                    for line in ocr_buf.getvalue().strip().splitlines():
                        self.log(f"[OCR] {line}")
                    if out_json.exists():
                        r.ocr_fallback_used = True
                        r.artifact_written_ok = True
                        if r.parse_status == "FAILED":
                            r.parse_status = "SUCCESS_WITH_PROTOCOL_ERROR"
                        self.log(f"[OCR Fallback] ✓ OCR 成功: {stem}")
                    else:
                        self.log(f"[OCR Fallback] ✗ OCR 失败: {stem}")
                    return pdf_path

                ocr_workers = min(2, len(needs_ocr_list))
                self.log(f"[OCR Fallback] 并发重跑: {len(needs_ocr_list)} 个文件, {ocr_workers} 并发")
                with ThreadPoolExecutor(max_workers=ocr_workers) as executor:
                    for pdf_path in executor.map(_ocr_one, needs_ocr_list):
                        if self.stop_event.is_set():
                            break

            total_ok = sum(1 for r in reports.values() if r.parse_status != "FAILED")
            self.log(f"[OCR Fallback] 最终成功 {total_ok}/{len(all_pdf_paths)}")

            still_failed = [p for p in all_pdf_paths if reports[p].parse_status == "FAILED"]
            if still_failed:
                self.log(f"[PyMuPDF Fallback] {len(still_failed)} 个文件仍失败，尝试 PyMuPDF 提取...")
                try:
                    import fitz as _fitz
                    for pdf_path in still_failed:
                        if self.stop_event.is_set():
                            break
                        r = reports[pdf_path]
                        raw_stem = Path(pdf_path).stem
                        if len(raw_stem) > 80:
                            import hashlib as _hl
                            _h = _hl.md5(raw_stem.encode()).hexdigest()[:8]
                            _ym = _YEAR_HASH_RE.match(raw_stem)
                            _prefix = _ym.group(1) if _ym else raw_stem[:10]
                            stem = f"{_prefix}_{_h}"
                        else:
                            stem = raw_stem
                        base = Path(output_dir) if output_dir else Path(pdf_path).parent
                        out_json = base / (stem + ".json")
                        images_dir = base / (stem + "_images")
                        try:
                            doc = _fitz.open(str(pdf_path))
                            kids = []
                            seen_xrefs = set()
                            images_dir.mkdir(parents=True, exist_ok=True)
                            img_count = 0
                            for page_num in range(len(doc)):
                                page = doc[page_num]
                                text_blocks = []
                                for block in page.get_text("dict")["blocks"]:
                                    if block.get("type") == 0:
                                        for line in block.get("lines", []):
                                            for span in line.get("spans", []):
                                                text_blocks.append({
                                                    "type": "text",
                                                    "content": span.get("text", ""),
                                                    "page number": page_num + 1,
                                                })
                                kids.extend(text_blocks)
                                for img_info in page.get_images(full=True):
                                    xref = img_info[0]
                                    if xref in seen_xrefs:
                                        continue
                                    seen_xrefs.add(xref)
                                    try:
                                        base_image = doc.extract_image(xref)
                                        w = base_image.get("width", 0)
                                        h = base_image.get("height", 0)
                                        ext = base_image.get("ext", "png")
                                        img_data = base_image.get("image", b"")
                                        if w < 50 or h < 50 or len(img_data) < 5120:
                                            continue
                                        fname = f"imageFile{img_count + 1}.{ext}"
                                        fpath = images_dir / fname
                                        with open(fpath, "wb") as f:
                                            f.write(img_data)
                                        kids.append({
                                            "type": "image",
                                            "source": f"{stem}_images/{fname}",
                                            "page number": page_num + 1,
                                            "bounding box": [0, 0, w, h],
                                        })
                                        img_count += 1
                                    except Exception:
                                        continue
                            doc.close()
                            if img_count > 0:
                                json_data = {"kids": kids, "title": raw_stem}
                                out_json.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
                                r.parse_status = "SUCCESS_WITH_PROTOCOL_ERROR"
                                r.artifact_written_ok = True
                                r.ocr_fallback_used = True
                                r.json_path = str(out_json)
                                self.log(f"[PyMuPDF Fallback] ✓ {raw_stem[:40]}")
                            else:
                                self.log(f"[PyMuPDF Fallback] ✗ {raw_stem[:40]}")
                        except Exception as e:
                            self.log(f"[PyMuPDF Fallback] ✗ {raw_stem[:40]}: {e}")
                except ImportError:
                    self.log("[PyMuPDF Fallback] fitz 未安装，跳过")

            for idx, pdf_path in enumerate(all_pdf_paths, 1):
                if self.stop_event.is_set():
                    self.log("用户请求停止，跳过剩余文件...")
                    break
                self.root.after(0, lambda i=idx, t=len(all_pdf_paths): self.preprocess_progress.configure(value=int(i/t*100)))
                self.status_var.set(f"后处理 ({idx}/{len(all_pdf_paths)}): {os.path.basename(pdf_path)}")
                r = reports[pdf_path]

                if Path(r.json_path).exists():
                    _raw_stem = Path(pdf_path).stem
                    if len(_raw_stem) > 80:
                        import hashlib as _hl2
                        _h2 = _hl2.md5(_raw_stem.encode()).hexdigest()[:8]
                        _ym2 = _YEAR_HASH_RE.match(_raw_stem)
                        _prefix2 = _ym2.group(1) if _ym2 else _raw_stem[:10]
                        _stem = f"{_prefix2}_{_h2}"
                    else:
                        _stem = _raw_stem
                    _base = Path(output_dir) if output_dir else Path(pdf_path).parent
                    _images_dir = _base / (_stem + "_images")
                    if not _images_dir.exists() or not any(_images_dir.iterdir()):
                        try:
                            import fitz as _fitz
                            self.log(f"[图片补提取] {_raw_stem[:40]}")
                            _doc = _fitz.open(str(pdf_path))
                            _images_dir.mkdir(parents=True, exist_ok=True)
                            _seen = set()
                            _ic = 0
                            for _pn in range(len(_doc)):
                                _page = _doc[_pn]
                                for _ii in _page.get_images(full=True):
                                    _xref = _ii[0]
                                    if _xref in _seen:
                                        continue
                                    _seen.add(_xref)
                                    try:
                                        _bi = _doc.extract_image(_xref)
                                        _w = _bi.get("width", 0)
                                        _h = _bi.get("height", 0)
                                        _ext = _bi.get("ext", "png")
                                        _data = _bi.get("image", b"")
                                        if _w < 50 or _h < 50 or len(_data) < 5120:
                                            continue
                                        _fn = f"imageFile{_ic + 1}.{_ext}"
                                        with open(_images_dir / _fn, "wb") as _f:
                                            _f.write(_data)
                                        _ic += 1
                                    except Exception:
                                        continue
                            _doc.close()
                        except ImportError:
                            pass

                if PREPROCESSOR_AVAILABLE and Path(r.json_path).exists():
                    pp_result = self._run_preprocessor(pdf_path)
                    if pp_result and pp_result.get("preprocess_status") == "SUCCESS":
                        r.preprocess_status = "SUCCESS"
                        r.mid_task_written = pp_result.get("mid_task_written", True)
                        r.mid_task_path = pp_result.get("mid_task_path", "")
                    else:
                        r.preprocess_status = "FAILED"
                        r.error_message = (pp_result or {}).get("error_message", "unknown")
                elif not PREPROCESSOR_AVAILABLE:
                    self.log("预处理模块不可用，跳过")
                else:
                    r.preprocess_status = "FAILED"
                    r.error_message = "json_not_found"

                if r.parse_status == "SUCCESS" and r.preprocess_status == "SUCCESS":
                    r.final_status = "COMPLETE"
                elif r.parse_status == "FAILED":
                    r.final_status = "FAILED"
                else:
                    r.final_status = "PARTIAL"

            self.file_reports = list(reports.values())
            n = len(self.file_reports)
            parse_success = sum(1 for r in self.file_reports if r.parse_status == "SUCCESS")
            parse_proto_err = sum(1 for r in self.file_reports if r.parse_status == "SUCCESS_WITH_PROTOCOL_ERROR")
            parse_fail = sum(1 for r in self.file_reports if r.parse_status == "FAILED")
            pp_success = sum(1 for r in self.file_reports if r.preprocess_status == "SUCCESS")
            pp_fail = sum(1 for r in self.file_reports if r.preprocess_status == "FAILED")
            final_complete = sum(1 for r in self.file_reports if r.final_status == "COMPLETE")
            final_partial = sum(1 for r in self.file_reports if r.final_status == "PARTIAL")
            final_fail = sum(1 for r in self.file_reports if r.final_status == "FAILED")

            self.log("\n" + "="*60)
            self.log(f"[BATCH SUMMARY] total={n} | parse_success={parse_success} | "
                     f"protocol_error={parse_proto_err} | parse_fail={parse_fail}")
            self.log(f"[BATCH SUMMARY] preprocess_success={pp_success} | preprocess_fail={pp_fail}")
            self.log(f"[BATCH SUMMARY] final: COMPLETE={final_complete} | PARTIAL={final_partial} | FAILED={final_fail}")
            self.log("-"*60)
            for r in self.file_reports:
                self.log(f"FINAL_STATUS | file={r.pdf_name} | parse={r.parse_status} | "
                         f"preprocess={r.preprocess_status} | final={r.final_status}")
            self.log("="*60)
            if pp_success > 0:
                self.root.after(0, lambda: self.extract_btn.config(state=tk.NORMAL))
            if final_fail > 0 or final_partial > 0:
                self.log(f"⚠ 批次包含 {final_fail} 个失败 + {final_partial} 个部分成功")
            if not self.stop_event.is_set():
                self.log("\n所有任务处理完毕")
                self.status_var.set(f"完成: {final_complete}/{n} 全成功")
            else:
                self.status_var.set("已停止")
        except Exception as e:
            self.log(f"发生严重错误: {str(e)}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            self.root.after(0, self.conversion_finished)

    def _run_preprocessor(self, pdf_path: str, report: Optional[FileProcessReport] = None) -> Dict[str, Any]:
        pdf = Path(pdf_path)
        output_dir = self.output_dir.get().strip() or None
        json_path, images_dir = _resolve_pdf_assets(pdf, output_dir)
        mid_json_dir_str = self.mid_json_output_dir.get().strip()
        if mid_json_dir_str:
            mid_json_dir = Path(mid_json_dir_str)
            mid_json_dir.mkdir(parents=True, exist_ok=True)
        else:
            mid_json_dir = Path(output_dir) if output_dir else pdf.parent

        result = {
            "preprocess_status": "FAILED",
            "mid_task_written": False,
            "mid_task_path": "",
            "preprocess_seconds": 0.0,
            "error_message": "",
        }
        start_time = time.time()

        self.log(f"[PREPROCESS][{pdf.stem}] json_path={json_path}")
        if not json_path.exists():
            result["error_message"] = f"missing_json={json_path}"
            result["preprocess_seconds"] = round(time.time() - start_time, 2)
            return result

        try:
            overrides = {
                "adaptive_chunking": {"enabled": False},
                "image_filter": {"require_caption_for_small": True},
            }
            out_dir = Path(output_dir) if output_dir else pdf.parent
            pre = NanozymePreprocessor(
                json_path=str(json_path),
                images_root=str(images_dir) if images_dir.exists() else None,
                output_root=str(out_dir),
                rulebook_path="rulebook.json",
                runtime_overrides=overrides,
                pdf_stem=pdf.stem,
                extraction_mode="single_main_nanozyme",
            )
            pre_buf = io.StringIO()
            with contextlib.redirect_stdout(pre_buf):
                pre.process()
                mid_json_path = mid_json_dir / f"{pdf.stem}_mid_task.json"
                mid = pre.to_mid_json(str(mid_json_path))

            captured_text = pre_buf.getvalue().strip()
            if captured_text:
                for line in captured_text.splitlines():
                    self.log(f"[PREPROCESS][{pdf.stem}] {line}")

            result.update(
                {
                    "preprocess_status": "SUCCESS",
                    "mid_task_written": mid_json_path.exists(),
                    "mid_task_path": str(mid_json_path),
                }
            )
            if not result["mid_task_written"]:
                result["preprocess_status"] = "FAILED"
                result["error_message"] = f"mid_task_missing={mid_json_path}"
            else:
                self.mid_json_path = str(mid_json_path)
                self.root.after(0, lambda: self.preprocess_status.config(text="状态: 预处理完成，可启动智能提取", foreground="green"))
                self.log(f"[PREPROCESS][{pdf.stem}] mid_task={mid_json_path.name}")
        except Exception as e:
            import traceback
            result["error_message"] = f"preprocess_exception={e}"
            self.log(f"[PREPROCESS][{pdf.stem}] failed: {e}")
            self.log(traceback.format_exc())
        finally:
            result["preprocess_seconds"] = round(time.time() - start_time, 2)
        return result

    def conversion_finished(self):
        self.preprocess_progress.configure(value=100)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.stop_event.clear()
        pp_success = sum(1 for r in self.file_reports if r.preprocess_status == "SUCCESS")
        if pp_success > 0:
            self.extract_btn.config(state=tk.NORMAL)

    def stop_conversion(self):
        self.stop_event.set()
        self.log("正在停止...")
        self.stop_btn.config(state=tk.DISABLED)

    def start_extraction(self):
        if not Path("config.yaml").exists():
            choice = messagebox.askyesnocancel(
                "配置缺失",
                "未找到 config.yaml 配置文件。\n\n"
                "点击「是」：自动生成模板配置文件（需手动填入API密钥）\n"
                "点击「否」：以规则模式提取（不调用 LLM/VLM）\n"
                "点击「取消」：返回\n\n"
                "提示：规则模式无需API密钥即可使用，但提取精度较低。\n"
                "      AI模式需配置DeepSeek/OpenAI等API密钥。"
            )
            if choice is None:
                return
            elif choice is True:
                self._generate_config_template()
                messagebox.showinfo("配置已生成",
                    "已生成 config.yaml 模板文件。\n\n"
                    "请用文本编辑器打开，填入API密钥后重新启动系统。\n"
                    "当前将以规则模式继续提取。")
            else:
                self.log("[提取] 规则模式提取（无 LLM/VLM）")

        success_reports = [
            r for r in self.file_reports
            if r.preprocess_status == "SUCCESS" and r.mid_task_path
        ]
        mid_json_paths = [r.mid_task_path for r in success_reports]

        if not mid_json_paths:
            if self.mid_json_path and Path(self.mid_json_path).exists():
                mid_json_paths = [self.mid_json_path]
                self.log(f"[提取] 使用单文件模式: {self.mid_json_path}")
            else:
                messagebox.showerror("错误", "未找到 mid_task.json，请先完成预处理")
                return

        self.extract_stop_event.clear()
        self.extract_btn.config(state=tk.DISABLED)
        self.start_btn.config(state=tk.DISABLED)
        self.stop_extract_btn.config(state=tk.NORMAL)
        self.extract_progress['value'] = 0
        self.extract_status.config(text=f"状态: 正在提取 (0/{len(mid_json_paths)})...", foreground="blue")

        force_reextract = self.force_reextract_var.get()
        self.extract_thread = threading.Thread(
            target=self.extract_worker,
            args=(mid_json_paths, force_reextract),
            daemon=True
        )
        self.extract_thread.start()

    def _generate_config_template(self):
        template = """# Nanozyme Extraction System Configuration
# Fill in your API keys below to enable AI-enhanced extraction

providers:
  llm:
    model: deepseek-chat
    base_url: https://api.deepseek.com/v1
    api_key: YOUR_DEEPSEEK_API_KEY
    max_tokens: 8192
    temperature: 0.1

  vlm:
    model: Qwen/Qwen2-VL-7B-Instruct
    base_url: https://api.siliconflow.cn/v1
    api_key: YOUR_SILICONFLOW_API_KEY
    max_tokens: 4096

pipeline:
  enable_llm: true
  enable_vlm: true
  enable_cache: true
  per_document_timeout: 600
  results_dir: extraction_results
"""
        try:
            with open("config.yaml", "w", encoding="utf-8") as f:
                f.write(template)
            self.log("[配置] 已生成 config.yaml 模板文件")
        except Exception as e:
            self.log(f"[配置] 生成配置文件失败: {e}")

    def stop_extraction(self):
        if messagebox.askyesno("确认停止", "确定要停止当前提取任务吗?"):
            self.extract_stop_event.set()
            self.stop_extract_btn.config(state=tk.DISABLED)
            self.log("[提取] 用户请求停止提取...")
            self.extract_status.config(text="状态: 正在停止...", foreground="orange")

    def extract_worker(self, mid_json_paths: List[str], force_reextract: bool = False):
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)

            from extraction_pipeline import ExtractionPipeline

            custom_output_dir = self.extracted_json_output_dir.get().strip()

            def progress_callback(msg: str, current: int = 0, total: int = 0, percent: int = None):
                if self.extract_stop_event.is_set():
                    raise KeyboardInterrupt("用户停止提取")
                self.root.after(0, lambda m=msg, c=current, t=total, p=percent: self.update_extract_progress(m, c, t, p))

            pipeline = ExtractionPipeline(
                output_dir=custom_output_dir if custom_output_dir else None,
                enable_cache=True
            )

            total = len(mid_json_paths)
            all_output_paths = []
            failed_files = []

            pending_paths = []
            for idx, mid_path in enumerate(mid_json_paths, 1):
                if self.extract_stop_event.is_set():
                    break
                if not force_reextract:
                    mid_stem = Path(mid_path).stem
                    if mid_stem.endswith("_mid_task"):
                        mid_stem = mid_stem[: -len("_mid_task")]
                    expected_name = f"{mid_stem}_extracted.json"
                    out_dir = Path(custom_output_dir) if custom_output_dir else pipeline.output_dir
                    existing = out_dir / expected_name
                    if existing.exists():
                        try:
                            with open(existing, 'r', encoding='utf-8') as ef:
                                json.load(ef)
                            self.log(f"[提取] 跳过已提取: {Path(mid_path).name}")
                            all_output_paths.append(str(existing))
                            continue
                        except (json.JSONDecodeError, OSError):
                            pass
                pending_paths.append(mid_path)

            if pending_paths and not self.extract_stop_event.is_set():
                max_workers = min(2, len(pending_paths))
                self.log(f"[提取] 并发提取: {len(pending_paths)} 个文件, {max_workers} 并发")
                done_count = total - len(pending_paths)

                def _extract_one(mid_path: str) -> Tuple[str, Optional[str], Optional[str]]:
                    stem = Path(mid_path).stem
                    try:
                        out_path = pipeline.process_mid_json_sync(
                            mid_path,
                            progress_callback=lambda msg, p=None: progress_callback(msg, 0, 0, p),
                            use_cache=not force_reextract,
                            extraction_mode=self._extraction_mode,
                        )
                        return (mid_path, out_path, None)
                    except Exception as e:
                        return (mid_path, None, str(e))

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_map = {
                        executor.submit(_extract_one, p): p
                        for p in pending_paths
                    }
                    for future in as_completed(future_map):
                        if self.extract_stop_event.is_set():
                            break
                        mid_path = future_map[future]
                        done_count += 1
                        self.root.after(0, lambda i=done_count, t=total, p=mid_path: self.extract_status.config(
                            text=f"状态: 正在提取 ({i}/{t}): {Path(p).name}...", fg="blue"))
                        try:
                            src, out_path, err = future.result()
                            if err:
                                self.log(f"[提取] ✗ {Path(src).name} 失败: {err}")
                                failed_files.append((src, err))
                            else:
                                all_output_paths.append(out_path)
                                self.log(f"[提取] ✓ {Path(src).name} -> {out_path}")
                        except Exception as e:
                            self.log(f"[提取] ✗ {Path(mid_path).name} 异常: {e}")
                            failed_files.append((mid_path, str(e)))

            if self.extract_stop_event.is_set():
                self.root.after(0, self.extraction_stopped)
                return

            if failed_files:
                self.root.after(0, lambda fps=failed_files: self.extraction_partially_finished(all_output_paths, fps))
            else:
                self.root.after(0, lambda outs=all_output_paths: self.extraction_batch_finished(outs))

        except KeyboardInterrupt:
            self.root.after(0, self.extraction_stopped)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.root.after(0, lambda err=str(e), traceback=tb: self.extraction_error(err, traceback))

    def update_extract_progress(self, msg: str, current: int = 0, total: int = 0, percent: int = None):
        self.extract_status.config(text=f"状态: {msg}")
        if total > 1 and percent is not None:
            base = int(((current - 1) / total) * 100)
            file_progress = int((percent / 100) * (100 / total))
            self.extract_progress['value'] = min(base + file_progress, 99)
        elif total > 1 and current > 0:
            self.extract_progress['value'] = int((current / total) * 100)
        elif percent is not None:
            self.extract_progress['value'] = percent
        self.log(f"[提取进度] {msg}" + (f" ({current}/{total})" if total > 1 else f" (进度: {percent}%)" if percent is not None else ""))

    def extraction_finished(self, out_path):
        self.extract_progress['value'] = 100
        self.extract_status.config(text="状态: 提取完成", foreground="green")
        self.extract_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_extract_btn.config(state=tk.DISABLED)
        self.view_result_btn.config(state=tk.NORMAL)
        self.extracted_json_path = out_path
        self.extracted_json_paths = [out_path] if out_path else []
        self.log("[提取] ===== 大模型提取流程完成 =====")
        self.log(f"[提取] 结果保存至: {out_path}")
        messagebox.showinfo("提取完成", f"结果已保存至:\n{out_path}")

    def extraction_batch_finished(self, output_paths: List[str]):
        self.extract_progress['value'] = 100
        n = len(output_paths)
        self.extract_status.config(text=f"状态: 全部完成 ({n}个文件)", fg="green")
        self.extract_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_extract_btn.config(state=tk.DISABLED)
        if output_paths:
            self.view_result_btn.config(state=tk.NORMAL)
        else:
            self.view_result_btn.config(state=tk.DISABLED)
        self.extracted_json_paths = output_paths
        self.extracted_json_path = output_paths[0] if output_paths else ""
        self.log("[提取] ===== 批量大模型提取全部完成 =====")
        for p in output_paths:
            self.log(f"[提取]   {p}")
        if output_paths:
            messagebox.showinfo("批量提取完成", f"已成功提取 {n} 个文件:\n" + "\n".join(Path(p).name for p in output_paths))

    def extraction_partially_finished(self, output_paths: List[str], failed_files: List[Tuple[str, str]]):
        n_ok = len(output_paths)
        n_fail = len(failed_files)
        self.extract_progress['value'] = int((n_ok / (n_ok + n_fail)) * 100)
        self.extract_status.config(text=f"状态: 部分完成 ({n_ok}成功/{n_fail}失败)", fg="orange")
        self.extract_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_extract_btn.config(state=tk.DISABLED)
        if output_paths:
            self.view_result_btn.config(state=tk.NORMAL)
        else:
            self.view_result_btn.config(state=tk.DISABLED)
        self.extracted_json_paths = output_paths
        self.extracted_json_path = output_paths[0] if output_paths else ""
        self.log(f"[提取] ===== 批量提取完成 ({n_ok}成功/{n_fail}失败) =====")
        self.log("[提取] 成功文件:")
        for p in output_paths:
            self.log(f"[提取]   ✓ {p}")
        self.log("[提取] 失败文件:")
        for path, err in failed_files:
            self.log(f"[提取]   ✗ {Path(path).name}: {err}")
        messagebox.showwarning(
            "部分失败",
            f"提取完成: {n_ok}个成功, {n_fail}个失败\n"
            f"成功文件: {', '.join(Path(p).name for p in output_paths)}\n"
            f"失败文件: {', '.join(Path(p).name for p, _ in failed_files)}"
        )
    
    def extraction_stopped(self):
        self.extract_progress['value'] = 0
        self.extract_status.config(text="状态: 已停止", foreground="orange")
        self.extract_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_extract_btn.config(state=tk.DISABLED)
        self.log("[提取] ===== 大模型提取已停止 =====")
        self.log("[提取] 用户手动停止提取,结果未保存")

    def extraction_error(self, error_msg, traceback_text):
        self.extract_status.config(text="状态: 提取失败", foreground="red")
        self.extract_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)
        self.log("[提取] ===== 大模型提取流程失败 =====")
        self.log(f"[提取] 错误信息: {error_msg}")
        self.log(f"[提取] 详细堆栈:\n{traceback_text}")
        messagebox.showerror("提取错误", f"提取过程发生错误:\n{error_msg}")

    def view_result(self):
        if not self.extracted_json_paths:
            messagebox.showinfo("提示", "没有可查看的结果文件")
            return
        if len(self.extracted_json_paths) > 1:
            selected = self._select_result_file(self.extracted_json_paths)
            if selected is None:
                return
            target_path = selected
        elif self.extracted_json_path and Path(self.extracted_json_path).exists():
            target_path = self.extracted_json_path
        else:
            messagebox.showwarning("提示", "请先完成提取")
            return

        with open(target_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        dialog = ResultReviewDialog(self.root, data, target_path,
                                    on_feedback=self.on_feedback_received)
        dialog.show()

    def _select_result_file(self, paths: List[str]) -> Optional[str]:
        selected = []
        top = tk.Toplevel(self.root)
        top.title("选择结果文件")
        top.geometry("500x300")
        
        listbox = tk.Listbox(top, selectmode=tk.SINGLE, width=60, height=15)
        listbox.pack(fill="both", expand=True, padx=10, pady=10)
        
        for p in paths:
            listbox.insert(tk.END, Path(p).name)
        
        def on_ok():
            idx = listbox.curselection()
            if idx:
                selected.append(paths[idx[0]])
            top.destroy()
        
        def on_cancel():
            top.destroy()
        
        btn_frame = ttk.Frame(top)
        btn_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(btn_frame, text="确定", command=on_ok).pack(side="left")
        ttk.Button(btn_frame, text="取消", command=on_cancel).pack(side="left", padx=5)
        
        top.grab_set()
        self.root.wait_window(top)
        return selected[0] if selected else None

    def on_feedback_received(self, feedback):
        self.log(f"[反馈] 用户反馈: {feedback}")


class ResultReviewDialog:
    def __init__(self, parent, data, file_path, on_feedback=None):
        self.parent = parent
        self.data = data
        self.file_path = file_path
        self.on_feedback = on_feedback
        self.dialog = None

    def show(self):
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(f"结果查看 - {Path(self.file_path).name}")
        self.dialog.geometry("900x600")
        
        main_frame = ttk.Frame(self.dialog)
        main_frame.pack(fill="both", expand=True, padx=8, pady=8)
        
        text_area = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, font=('Consolas', 10))
        text_area.pack(fill="both", expand=True)
        text_area.insert(tk.END, json.dumps(self.data, ensure_ascii=False, indent=2))
        text_area.config(state=tk.DISABLED)
        
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=5)
        
        ttk.Button(btn_frame, text="复制到剪贴板", command=self.copy_to_clipboard).pack(side="left")
        ttk.Button(btn_frame, text="打开所在目录", command=self.open_directory).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="关闭", command=self.dialog.destroy).pack(side="right")
        
        self.dialog.grab_set()

    def copy_to_clipboard(self):
        json_str = json.dumps(self.data, ensure_ascii=False, indent=2)
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(json_str)
        messagebox.showinfo("提示", "已复制到剪贴板")

    def open_directory(self):
        dir_path = os.path.dirname(self.file_path)
        if os.path.exists(dir_path):
            os.startfile(dir_path)


def main():
    root = tk.Tk()
    app = NanozymeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
