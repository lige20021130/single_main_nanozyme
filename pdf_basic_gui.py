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
import yaml
import logging

# 导入升级模块
try:
    from config_manager import ConfigManager
    CONFIG_MANAGER_AVAILABLE = True
except ImportError:
    CONFIG_MANAGER_AVAILABLE = False
    print("警告: 未找到 config_manager 模块，将使用手动 YAML 读取")

try:
    from logging_setup import setup_logging
    LOGGING_SETUP_AVAILABLE = True
except ImportError:
    LOGGING_SETUP_AVAILABLE = False
    print("警告: 未找到 logging_setup 模块，将使用默认日志配置")

# 导入处理层（假设在同一目录）
try:
    from nanozyme_preprocessor_midjson import NanozymePreprocessor
    PREPROCESSOR_AVAILABLE = True
except ImportError:
    PREPROCESSOR_AVAILABLE = False
    print("警告: 未找到 nanozyme_preprocessor_midjson 模块，预处理功能不可用")


def _resolve_pdf_assets(pdf_path: Path, output_dir: Optional[str]) -> Tuple[Path, Path]:
    """推导指定 PDF 的 JSON 和图片目录（GUI 与 preprocessor 共享规则）。

    规则：
      - output_dir 设置时：   json 在 <output_dir>/<stem>.json，图片在 <output_dir>/<stem>_images/
      - output_dir 未设置时： json 在 <pdf_parent>/<stem>.json，图片在 <pdf_parent>/<stem>_images/
    """
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


class PDFBasicGUI:
    # ── 固定默认 Profile（数字版英文纳米酶论文最优配置）──────────────────────
    DEFAULT_PROFILE = {
        "format": "json",
        "use_struct_tree": True,
        "reading_order": "xycut",
        "image_output": "external",
        "image_format": "png",
        "hybrid": "docling-fast",
        "hybrid_mode": "auto",          # 不默认开启 full/enrich_picture
        "hybrid_url": "http://localhost:5002",
        "hybrid_timeout": "60000",
        "hybrid_fallback": True,
        "table_method": "default",
    }
    # ── 服务器启动命令（固定，不再依赖用户勾选）──────────────────────────────
    SERVER_CMD_DEFAULT = ["opendataloader-pdf-hybrid", "--port=5002"]
    SERVER_CMD_OCR = ["opendataloader-pdf-hybrid", "--port=5002",
                      "--force-ocr", "--ocr-lang", "en"]
    # enrich-picture 专用命令留作备用，不放 GUI
    # SERVER_CMD_ENRICH = ["opendataloader-pdf-hybrid", "--port=5002",
    #                      "--enrich-picture-description"]

    def __init__(self, root):
        self.root = root
        self.root.title("纳米酶文献工作台")
        self.root.geometry("860x680")
        self.root.resizable(True, True)

        # 服务器进程
        self.server_process = None
        self.server_port = 5002
        self.server_ready = False
        self.server_mode = None  # "standard" | "ocr" | None

        # 变量（只保留必要的）
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

        # 大模型配置信息
        self.llm_config = None
        self.vlm_config = None

        self.create_widgets()
        self.log_queue = []
        self.update_log()

        # 加载大模型配置(在 widgets 创建后)
        self.load_model_config()

        # 设置日志处理器,将 logging 日志转发到 GUI
        self.setup_logging_handler()

    def create_widgets(self):
        style = ttk.Style()
        style.configure("Status.TLabel", font=('Arial', 9))
        style.configure("Header.TLabel", font=('Arial', 10, 'bold'))
        style.configure("Phase.TLabel", font=('Arial', 9), padding=3)

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

        # ── 中部：使用 Notebook 分页 ──────────────────────────────────────────
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill="both", expand=True, pady=4)

        # Tab 1: 文件与转换
        file_tab = ttk.Frame(notebook, padding=6)
        notebook.add(file_tab, text="  文件与转换  ")

        input_frame = ttk.LabelFrame(file_tab, text="输入设置", padding=5)
        input_frame.pack(fill="x", pady=3)
        ttk.Label(input_frame, text="PDF 文件或文件夹:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(input_frame, textvariable=self.input_path, width=60).grid(row=0, column=1, padx=5, columnspan=2, sticky="ew")
        ttk.Button(input_frame, text="选择文件", command=self.select_files).grid(row=0, column=3, padx=2)
        ttk.Button(input_frame, text="选择文件夹", command=self.select_folder).grid(row=0, column=4, padx=2)
        ttk.Checkbutton(input_frame, text="递归处理子文件夹", variable=self.recursive).grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(input_frame, text="输出目录:").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(input_frame, textvariable=self.output_dir, width=60).grid(row=2, column=1, padx=5, columnspan=2, sticky="ew")
        ttk.Button(input_frame, text="选择目录", command=self.select_output_dir).grid(row=2, column=3, padx=2, columnspan=2)
        input_frame.columnconfigure(1, weight=1)

        server_frame = ttk.LabelFrame(file_tab, text="PDF 解析服务器", padding=5)
        server_frame.pack(fill="x", pady=3)
        sf_inner = ttk.Frame(server_frame)
        sf_inner.pack(fill="x")
        ttk.Button(sf_inner, text="启动服务器", command=self.start_server).pack(side="left", padx=3)
        ttk.Button(sf_inner, text="停止服务器", command=self.stop_server).pack(side="left", padx=3)
        self.server_status = ttk.Label(sf_inner, text="● 未启动", foreground="red", style="Status.TLabel")
        self.server_status.pack(side="left", padx=15)
        ttk.Label(sf_inner, text="docling-fast | auto OCR fallback", foreground="gray").pack(side="right", padx=5)

        convert_frame = ttk.Frame(file_tab)
        convert_frame.pack(fill="x", pady=5)
        self.start_btn = ttk.Button(convert_frame, text="▶ 开始转换", command=self.start_conversion)
        self.start_btn.pack(side="left", padx=5)
        self.stop_btn = ttk.Button(convert_frame, text="■ 停止", command=self.stop_conversion, state=tk.DISABLED)
        self.stop_btn.pack(side="left", padx=5)
        self.progress = ttk.Progressbar(convert_frame, mode='determinate', maximum=100, length=300)
        self.progress.pack(side="left", padx=10, fill="x", expand=True)

        # Tab 2: 智能提取
        extract_tab = ttk.Frame(notebook, padding=6)
        notebook.add(extract_tab, text="  智能提取  ")

        model_info_frame = ttk.LabelFrame(extract_tab, text="大模型状态", padding=5)
        model_info_frame.pack(fill="x", pady=3)

        llm_row = ttk.Frame(model_info_frame)
        llm_row.pack(fill="x", pady=2)
        ttk.Label(llm_row, text="LLM:", font=('Arial', 9, 'bold'), width=6).pack(side="left")
        self.text_llm_label = ttk.Label(llm_row, text="加载中...", foreground="gray")
        self.text_llm_label.pack(side="left", padx=5, fill="x", expand=True)

        vlm_row = ttk.Frame(model_info_frame)
        vlm_row.pack(fill="x", pady=2)
        ttk.Label(vlm_row, text="VLM:", font=('Arial', 9, 'bold'), width=6).pack(side="left")
        self.vlm_label = ttk.Label(vlm_row, text="加载中...", foreground="gray")
        self.vlm_label.pack(side="left", padx=5, fill="x", expand=True)

        model_btn_row = ttk.Frame(model_info_frame)
        model_btn_row.pack(fill="x", pady=2)
        ttk.Button(model_btn_row, text="测试 API", command=self.test_model_connection).pack(side="left", padx=3)
        ttk.Button(model_btn_row, text="刷新配置", command=self.load_model_config).pack(side="left", padx=3)

        mode_frame = ttk.LabelFrame(extract_tab, text="提取设置", padding=5)
        mode_frame.pack(fill="x", pady=3)

        mode_row = ttk.Frame(mode_frame)
        mode_row.pack(fill="x", pady=2)
        ttk.Label(mode_row, text="提取模式: 单主纳米酶").pack(side="left", padx=5)

        output_row = ttk.Frame(mode_frame)
        output_row.pack(fill="x", pady=2)
        ttk.Label(output_row, text="中间JSON:").pack(side="left", padx=5)
        ttk.Entry(output_row, textvariable=self.mid_json_output_dir, width=40).pack(side="left", padx=5)
        ttk.Button(output_row, text="选择", command=self.select_mid_json_output).pack(side="left", padx=2)

        output_row2 = ttk.Frame(mode_frame)
        output_row2.pack(fill="x", pady=2)
        ttk.Label(output_row2, text="提取结果:").pack(side="left", padx=5)
        ttk.Entry(output_row2, textvariable=self.extracted_json_output_dir, width=40).pack(side="left", padx=5)
        ttk.Button(output_row2, text="选择", command=self.select_extracted_json_output).pack(side="left", padx=2)

        if not PREPROCESSOR_AVAILABLE:
            ttk.Label(mode_frame, text="⚠ 预处理模块未找到", foreground="red").pack(anchor="w", pady=2)

        extract_btn_frame = ttk.Frame(mode_frame)
        extract_btn_frame.pack(fill="x", pady=5)
        self.extract_btn = ttk.Button(extract_btn_frame, text="▶ 启动提取", command=self.start_extraction, state=tk.DISABLED)
        self.extract_btn.pack(side="left", padx=5)
        self.stop_extract_btn = ttk.Button(extract_btn_frame, text="■ 停止", command=self.stop_extraction, state=tk.DISABLED)
        self.stop_extract_btn.pack(side="left", padx=5)
        self.force_reextract_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(extract_btn_frame, text="强制重新提取", variable=self.force_reextract_var).pack(side="left", padx=5)
        self.view_result_btn = ttk.Button(extract_btn_frame, text="查看结果", command=self.view_result, state=tk.DISABLED)
        self.view_result_btn.pack(side="left", padx=5)

        self.extract_status = ttk.Label(mode_frame, text="状态: 等待预处理完成", foreground="gray")
        self.extract_status.pack(anchor="w", padx=5, pady=2)
        self.extract_progress = ttk.Progressbar(mode_frame, mode='determinate')
        self.extract_progress.pack(fill="x", padx=5, pady=3)

        # Tab 3: 运行日志
        log_tab = ttk.Frame(notebook, padding=6)
        notebook.add(log_tab, text="  运行日志  ")

        log_btn_frame = ttk.Frame(log_tab)
        log_btn_frame.pack(fill="x")
        ttk.Button(log_btn_frame, text="清除日志", command=lambda: self.log_text.delete('1.0', tk.END)).pack(side="right", padx=2)

        self.log_text = scrolledtext.ScrolledText(log_tab, height=12, wrap=tk.WORD, font=('Consolas', 9))
        self.log_text.pack(fill="both", expand=True, pady=3)
        self.log_text.tag_config("error", foreground="red")
        self.log_text.tag_config("warn", foreground="orange")
        self.log_text.tag_config("info", foreground="#0066cc")

        # ── 底部状态栏 ────────────────────────────────────────────────────────
        status_bar = ttk.Frame(main_frame)
        status_bar.pack(fill="x", pady=(2, 0))
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_bar, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W,
                  style="Status.TLabel").pack(side="left", fill="x", expand=True, padx=2)
        self.file_count_var = tk.StringVar(value="")
        ttk.Label(status_bar, textvariable=self.file_count_var, relief=tk.SUNKEN, anchor=tk.E,
                  style="Status.TLabel", width=20).pack(side="right", padx=2)

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
        """加载并显示大模型配置信息（优先使用 ConfigManager，失败时回退到手动 YAML 读取）"""
        try:
            # 优先使用 ConfigManager
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
            
            # 更新显示 - 只显示配置信息,不表示连通性
            self.text_llm_label.config(text=f"模型: {llm_model} | API: {llm_url} | 密钥: {llm_api_set} (点击'测试 API'验证)",
                foreground="blue" if llm_api_set == '✓' else "red"
            )
            self.vlm_label.config(text=f"模型: {vlm_model} | API: {vlm_url} | 密钥: {vlm_api_set} (点击'测试 API'验证)",
                foreground="blue" if vlm_api_set == '✓' else "red"
            )
            
            self.log("[配置] 大模型配置已加载,请点击'测试 API'验证连通性")
            
        except Exception as e:
            self.text_llm_label.config(text=f"加载失败: {str(e)}", foreground="red")
            self.vlm_label.config(text=f"加载失败: {str(e)}", foreground="red")
            self.log(f"[配置] 加载大模型配置失败: {e}")
    
    def _load_model_config_fallback(self):
        """手动 YAML 读取配置（fallback）"""
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
            text=f"模型: {llm_model} | API: {llm_url} | 密钥: {llm_api_set} (点击'测试 API'验证)",
            foreground="blue" if llm_api_set == '✓' else "red"
        )
        self.vlm_label.config(
            text=f"模型: {vlm_model} | API: {vlm_url} | 密钥: {vlm_api_set} (点击'测试 API'验证)",
            foreground="blue" if vlm_api_set == '✓' else "red"
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
                    msg = f"✓ {llm_model} - {text_result['message']}"
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
                    msg = f"✓ {vlm_model} - {vision_result['message']}"
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
        """设置日志处理器,将 logging 输出到 GUI（集成统一日志模块）"""
        # 根治 pin_memory warning：在 root logger 上挂 Filter，全局压制
        class _PinMemoryFilter(logging.Filter):
            def filter(self, record):
                if record.levelno == logging.WARNING and 'pin_memory' in record.getMessage():
                    return False
                return True
        logging.getLogger().addFilter(_PinMemoryFilter())

        # 先通过 logging_setup 初始化基础日志配置（文件日志、模块级别等）
        if LOGGING_SETUP_AVAILABLE:
            try:
                setup_logging(level=logging.INFO, log_file="ocr_gui.log", use_colors=False)
                self.log("[系统] 统一日志模块已初始化（含文件日志: ocr_gui.log）")
            except Exception as e:
                self.log(f"[系统] 统一日志初始化失败，使用默认配置: {e}")
        
        # 添加 GUI 日志处理器（将 logging 转发到 GUI 日志窗口）
        class GUILogHandler(logging.Handler):
            def __init__(self, gui_instance):
                super().__init__()
                self.gui = gui_instance
                
            def emit(self, record):
                log_msg = self.format(record)
                # pin_memory on CPU 是无害 warning，归类为 benign 避免误导
                if record.levelno == logging.WARNING and 'pin_memory' in log_msg:
                    if log_msg not in self.gui._benign_warning_cache:
                        self.gui._benign_warning_cache.add(log_msg)
                        self.gui.log(f"[BENIGN] {log_msg}")
                    return
                # 根据日志级别添加前缀
                if record.levelno >= logging.ERROR:
                    prefix = "[ERROR]"
                elif record.levelno >= logging.WARNING:
                    prefix = "[WARN]"
                elif record.levelno >= logging.INFO:
                    prefix = "[INFO]"
                else:
                    prefix = "[DEBUG]"
                self.gui.log(f"{prefix} {log_msg}")
        
        # 创建并配置处理器
        handler = GUILogHandler(self)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        
        # 添加到根日志器
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)
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
        self.log_queue.append((msg + "\n", tag))

    def update_log(self):
        if self.log_queue:
            for text, tag in self.log_queue:
                self.log_text.insert(tk.END, text, tag if tag else ())
            self.log_queue.clear()
            self.log_text.see(tk.END)
        self.root.after(100, self.update_log)

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
        """选择后处理 JSON 输出目录"""
        folder = filedialog.askdirectory(title="选择中间 JSON 输出目录")
        if folder:
            self.mid_json_output_dir.set(folder)
            self.log(f"[配置] 中间 JSON 输出目录: {folder}")

    def select_extracted_json_output(self):
        """选择大模型提取 JSON 输出目录"""
        folder = filedialog.askdirectory(title="选择提取结果输出目录")
        if folder:
            self.extracted_json_output_dir.set(folder)
            self.log(f"[配置] 提取结果输出目录: {folder}")

    def start_server(self):
        if self.server_process and self.server_process.poll() is None:
            messagebox.showinfo("提示", "服务器已在运行中")
            return
        if self.server_ready:
            self.log("[服务器] 服务器已就绪，无需重启")
            return
        self.log("[服务器] 启动中...")
        self.server_status.config(text="● 启动中", foreground="orange")
        self.set_phase_status("server", "running")
        threading.Thread(target=self._server_worker, daemon=True).start()

    def _server_worker(self):
        cmd = self.SERVER_CMD_DEFAULT
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "gbk"
            env["JAVA_TOOL_OPTIONS"] = "-Dfile.encoding=UTF-8"
            env["HF_HUB_OFFLINE"] = "1"
            env["PYTHONWARNINGS"] = "ignore:.*pin_memory.*:UserWarning"
            self.server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='gbk',
                errors='replace',
                env=env,
            )
            self.log(f"[服务器] 进程已启动 PID={self.server_process.pid}")

            def read_output():
                for line in self.server_process.stdout:
                    self.log(f"[服务器] {line.strip()}")

            threading.Thread(target=read_output, daemon=True).start()

            import urllib.request
            for attempt in range(60):
                if self.server_process.poll() is not None:
                    self.log(f"[服务器] 进程意外退出，返回码={self.server_process.returncode}")
                    self.root.after(0, lambda: self._on_server_stopped())
                    return
                try:
                    r = urllib.request.urlopen("http://localhost:5002/health", timeout=2)
                    if r.status == 200:
                        self.server_ready = True
                        self.root.after(0, lambda: self._on_server_ready())
                        return
                except Exception:
                    pass
                time.sleep(1)

            self.log("[服务器] 等待超时(60s)，服务器可能未正常启动")
            self.root.after(0, lambda: self._on_server_timeout())

        except Exception as e:
            self.log(f"[服务器] 启动失败: {e}")
            self.server_process = None
            self.root.after(0, lambda: self._on_server_error(str(e)))

    def _on_server_ready(self):
        self.server_status.config(text="● 运行中", foreground="green")
        self.set_phase_status("server", "ok")
        self.log("[服务器] ✓ 服务器已就绪 (http://localhost:5002/health)")

    def _on_server_stopped(self):
        self.server_ready = False
        self.server_process = None
        self.server_status.config(text="● 已停止", foreground="red")
        self.set_phase_status("server", "error")
        self.log("[服务器] ✗ 服务器进程已退出")

    def _on_server_timeout(self):
        self.server_status.config(text="● 启动超时", foreground="orange")
        self.set_phase_status("server", "error")
        self.log("[服务器] ⚠ 启动超时，请检查日志")

    def _on_server_error(self, msg):
        self.server_ready = False
        self.server_process = None
        self.server_status.config(text="● 启动失败", foreground="red")
        self.set_phase_status("server", "error")
        self.log(f"[服务器] ✗ 启动失败: {msg}")

    def stop_server(self):
        if self.server_process and self.server_process.poll() is None:
            self.server_process.terminate()
            self.log("已发送终止信号")
            self.server_status.config(text="● 停止中", foreground="orange")
            self.server_mode = None
        else:
            self.log("服务器未运行")

    def _needs_ocr_fallback(self, json_path: str) -> Tuple[bool, str]:
        """自动判定解析后的 JSON 是否需要 OCR fallback。

        判定信号（任一满足即返回 True）：
          1. kids 中 paragraph/heading/list 总数 < 8
          2. 前 2 页可读正文总字符 < 800
          3. 文本总字符数 < 1200
          4. 图片节点占绝对多数 (>60%)
          5. 文档页数>1 但抽出正文的页极少
        """
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
        if self.server_ready:
            return
        if self.server_process and self.server_process.poll() is None:
            import urllib.request
            try:
                r = urllib.request.urlopen("http://localhost:5002/health", timeout=3)
                if r.status == 200:
                    self.server_ready = True
                    self.server_status.config(text="● 运行中", foreground="green")
                    self.set_phase_status("server", "ok")
                    self.log("[服务器] 已有服务器在运行")
                    return
            except Exception:
                pass
        self.log("[服务器] 服务器未就绪，正在启动...")
        self.server_status.config(text="● 启动中", foreground="orange")
        self.set_phase_status("server", "running")
        import urllib.request
        cmd = self.SERVER_CMD_DEFAULT
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "gbk"
            env["JAVA_TOOL_OPTIONS"] = "-Dfile.encoding=UTF-8"
            env["HF_HUB_OFFLINE"] = "1"
            env["PYTHONWARNINGS"] = "ignore:.*pin_memory.*:UserWarning"
            self.server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='gbk',
                errors='replace',
                env=env,
            )
            self.log(f"[服务器] 进程已启动 PID={self.server_process.pid}")

            def read_output():
                for line in self.server_process.stdout:
                    self.log(f"[服务器] {line.strip()}")

            threading.Thread(target=read_output, daemon=True).start()

            for attempt in range(60):
                if self.server_process.poll() is not None:
                    raise RuntimeError(f"服务器进程意外退出，返回码={self.server_process.returncode}")
                try:
                    r = urllib.request.urlopen("http://localhost:5002/health", timeout=2)
                    if r.status == 200:
                        self.server_ready = True
                        self.root.after(0, lambda: self._on_server_ready())
                        self.log("[服务器] ✓ 服务器已就绪")
                        return
                except Exception:
                    pass
                time.sleep(1)
            self.log("[服务器] ⚠ 启动超时")
        except Exception as e:
            self.log(f"[服务器] 启动失败: {e}")
            self.server_process = None
            self.root.after(0, lambda: self._on_server_error(str(e)))
            raise

    def start_conversion(self):
        input_path = self.input_path.get().strip()
        if not input_path:
            messagebox.showerror("错误", "请选择 PDF 文件或文件夹")
            return
        if not self.server_process or self.server_process.poll() is not None:
            if messagebox.askyesno("提示", "AI 后端未启动，是否自动启动？"):
                self._ensure_server(mode="standard")
                self.root.after(3000, self._do_conversion)
                return
            else:
                return
        self._do_conversion()

    def _do_conversion(self):
        self.start_btn.config(state=tk.DISABLED)
        self.extract_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.root.after(0, lambda: self.progress.configure(value=0))
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
            self.root.after(0, lambda: self.progress.configure(value=5))

            # ── 初始化每文件账本 ──────────────────────────────────
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

            # ── 阶段 A：Python API 批量解析 ──────────────────────
            capture_buf = io.StringIO()
            with contextlib.redirect_stdout(capture_buf):
                try:
                    kwargs = dict(self.DEFAULT_PROFILE)
                    kwargs["input_path"] = all_pdf_paths
                    if output_dir:
                        kwargs["output_dir"] = output_dir
                    self.log(f"[解析] [Python API] convert kwargs: {kwargs}")
                    self.log("[解析] [Python API] 开始调用 opendataloader_pdf.convert ...")
                    import opendataloader_pdf
                    os.environ["PYTHONIOENCODING"] = "utf-8"
                    opendataloader_pdf.convert(**kwargs)
                    self.log(f"[解析] [Python API] ✓ 批量解析完成 ({len(all_pdf_paths)} 个 PDF)")
                    for pdf_path in all_pdf_paths:
                        r = reports[pdf_path]
                        r.server_convert_ok = True
                        r.response_parse_ok = True

                except UnicodeDecodeError as ude:
                    self.log(f"[解析] [Python API] UnicodeDecodeError (协议错误): {ude}")
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
                            self.log(f"[解析] ⚠ {r.pdf_name}: parse=SUCCESS_WITH_PROTOCOL_ERROR (json落盘)")
                        else:
                            r.artifact_written_ok = False
                            r.parse_status = "FAILED"
                            missing.append(pdf_path)
                            self.log(f"[解析] ✗ {r.pdf_name}: parse=FAILED (json未生成)")

                    if missing:
                        self.log(f"[解析] [CLI Fallback] 对 {len(missing)} 个缺失文件启动 CLI 补跑...")
                        for mpath in missing:
                            r = reports[mpath]
                            stem = Path(mpath).stem
                            base = Path(output_dir) if output_dir else Path(mpath).parent
                            out_json = base / (stem + ".json")
                            cmd = ["opendataloader-pdf", str(mpath), "--format=json", f"--output-dir={str(base)}"]
                            self.log(f"[解析] [CLI Fallback] 补跑: {stem}")
                            try:
                                fe = os.environ.copy()
                                fe["PYTHONIOENCODING"] = "gbk"
                                result = subprocess.run(cmd, capture_output=True, text=True,
                                                        encoding='gbk', errors='replace', env=fe, timeout=600)
                                if out_json.exists():
                                    r.artifact_written_ok = True
                                    r.parse_status = "SUCCESS_WITH_PROTOCOL_ERROR"
                                    r.ocr_fallback_used = True
                                    self.log(f"[解析] [CLI Fallback] ✓ {stem}: parse=SUCCESS_WITH_PROTOCOL_ERROR")
                                else:
                                    self.log(f"[解析] [CLI Fallback] ✗ {stem}: parse=FAILED (rc={result.returncode})")
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
            os.environ.pop("PYTHONIOENCODING", None)

            if self.stop_event.is_set():
                self.log("用户请求停止，跳过剩余文件...")
                return
            self.root.after(0, lambda: self.progress.configure(value=40))

            # ── 对 parse_status 未设置的文件做最终判定 ───────────
            for pdf_path in all_pdf_paths:
                r = reports[pdf_path]
                if r.parse_status == "FAILED" and Path(r.json_path).exists():
                    # response_parse_ok was True (no exception), artifact exists
                    r.parse_status = "SUCCESS"
                    r.artifact_written_ok = True

            # ── 阶段 B：OCR fallback 判定 ─────────────────────────
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
            else:
                self.log("[OCR Fallback] 无需 OCR fallback")

            # ── 阶段 C：OCR 重跑 ─────────────────────────────────
            if needs_ocr_list and not self.stop_event.is_set():
                self._ensure_server(mode="ocr")
                for pdf_path, _reason in needs_ocr_list:
                    if self.stop_event.is_set():
                        self.log("用户请求停止，跳过剩余文件...")
                        break
                    r = reports[pdf_path]
                    stem = Path(pdf_path).stem
                    base = Path(output_dir) if output_dir else Path(pdf_path).parent
                    out_json = base / (stem + ".json")
                    self.log(f"[OCR Fallback] 重跑: {stem}")
                    ocr_buf = io.StringIO()
                    with contextlib.redirect_stdout(ocr_buf):
                        try:
                            os.environ["PYTHONIOENCODING"] = "utf-8"
                            ocr_kwargs = dict(self.DEFAULT_PROFILE)
                            ocr_kwargs["input_path"] = [str(pdf_path)]
                            ocr_kwargs["output_dir"] = str(base)
                            ocr_kwargs["hybrid_timeout"] = "120000"
                            import opendataloader_pdf
                            opendataloader_pdf.convert(**ocr_kwargs)
                        except UnicodeDecodeError:
                            self.log(f"[OCR Fallback] UnicodeDecodeError，检查输出...")
                        except Exception as e:
                            self.log(f"[OCR Fallback] 异常: {stem}: {e}")
                        finally:
                            os.environ.pop("PYTHONIOENCODING", None)
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

                ocr_ok = sum(1 for pdf_path, _ in needs_ocr_list if reports[pdf_path].ocr_fallback_used)
                self.log(f"[OCR Fallback] OCR 补跑成功 {ocr_ok} | 失败 {len(needs_ocr_list)-ocr_ok}")

            total_ok = sum(1 for r in reports.values() if r.parse_status != "FAILED")
            self.log(f"[OCR Fallback] 最终成功 {total_ok}/{len(all_pdf_paths)}")

            # ── 阶段 D：预处理 ────────────────────────────────────
            for idx, pdf_path in enumerate(all_pdf_paths, 1):
                if self.stop_event.is_set():
                    self.log("用户请求停止，跳过剩余文件...")
                    break
                self.root.after(0, lambda i=idx, t=len(all_pdf_paths): self.progress.configure(value=int(i/t*100)))
                self.status_var.set(f"后处理 ({idx}/{len(all_pdf_paths)}): {os.path.basename(pdf_path)}")
                r = reports[pdf_path]
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

            # ── 批次 summary ──────────────────────────────────────
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
                self.log(f"⚠ 批次包含 {final_fail} 个失败 + {final_partial} 个部分成功，请检查上方明细")
            if not self.stop_event.is_set():
                self.log("\n所有任务处理完毕（见上方 BATCH SUMMARY）")
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

        self.log(f"[PREPROCESS][{pdf.stem}] json_path={json_path} exists={json_path.exists()}")
        self.log(f"[PREPROCESS][{pdf.stem}] images_dir={images_dir} exists={images_dir.exists()}")
        if not json_path.exists():
            result["error_message"] = f"missing_json={json_path}"
            result["preprocess_seconds"] = round(time.time() - start_time, 2)
            self.log(f"[PREPROCESS][{pdf.stem}] skip missing json")
            return result

        if not images_dir.exists():
            self.log(f"[PREPROCESS][{pdf.stem}] warning missing images_dir, continue with text-only tolerance")

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
                self.root.after(0, lambda: self.extract_status.config(text="状态: 已就绪，可启动大模型提取", foreground="green"))
                self.log(
                    f"[PREPROCESS][{pdf.stem}] mid_task={mid_json_path.name} "
                    f"chunks={len(mid.get('llm_task', {}).get('chunks', []))} "
                    f"vlm_tasks={len(mid.get('vlm_tasks', []))}"
                )
                diagnostics = getattr(pre, "diagnostics", {})
                if diagnostics:
                    self.log(f"[PREPROCESS][{pdf.stem}] image_key_sources={diagnostics.get('image_key_sources', {})}")
                    self.log(f"[PREPROCESS][{pdf.stem}] caption_match={diagnostics.get('caption_match', {})}")
                    self.log(f"[PREPROCESS][{pdf.stem}] dropped_text={diagnostics.get('dropped_text_reasons', {})}")
                    self.log(f"[PREPROCESS][{pdf.stem}] chunk_stats={diagnostics.get('chunk_stats', {})}")
        except Exception as e:
            import traceback
            result["error_message"] = f"preprocess_exception={e}"
            self.log(f"[PREPROCESS][{pdf.stem}] failed: {e}")
            self.log(traceback.format_exc())
        finally:
            result["preprocess_seconds"] = round(time.time() - start_time, 2)
        return result

    def conversion_finished(self):
        self.progress.configure(value=100)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.stop_event.clear()
        pp_success = sum(1 for r in self.file_reports if r.preprocess_status == "SUCCESS")
        if pp_success > 0:
            self.extract_btn.config(state=tk.NORMAL)

    def _terminate_convert_process(self, process, force: bool = False):
        if not process or process.poll() is not None:
            return
        try:
            if os.name == "nt":
                cmd = ["taskkill", "/PID", str(process.pid), "/T", "/F"]
                subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="gbk",
                    errors="replace",
                    timeout=10,
                )
            elif force:
                process.kill()
            else:
                process.terminate()
        except Exception as e:
            mode = "force_kill" if force else "terminate"
            self.log(f"[解析] {mode} failed: {e}")

    def stop_conversion(self):
        self.stop_event.set()
        self.log("正在停止... 后续阶段将跳过")
        self.stop_btn.config(state=tk.DISABLED)

    def start_extraction(self):
        """启动大模型提取（支持单文件和批量模式）"""
        # 检查 config.yaml 是否存在
        if not Path("config.yaml").exists():
            messagebox.showwarning("配置缺失",
                "未找到 config.yaml 配置文件。\n"
                "请先在程序目录创建该文件并填入 API 密钥后重试。")
            return

        # 收集所有预处理成功的 mid_task 文件
        success_reports = [
            r for r in self.file_reports
            if r.preprocess_status == "SUCCESS" and r.mid_task_path
        ]
        mid_json_paths = [r.mid_task_path for r in success_reports]

        if not mid_json_paths:
            if self.mid_json_path and Path(self.mid_json_path).exists():
                mid_json_paths = [self.mid_json_path]
                self.log(f"[提取] 无 file_reports，使用单文件模式: {self.mid_json_path}")
            else:
                messagebox.showerror("错误", "未找到 mid_task.json，请先完成预处理")
                return

        if len(mid_json_paths) == 1:
            self.log(f"[提取] 单文件模式: {mid_json_paths[0]}")
        else:
            self.log(f"[提取] 批量模式: {len(mid_json_paths)} 个文件")
            for p in mid_json_paths:
                self.log(f"[提取]   - {Path(p).name}")

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
    
    def stop_extraction(self):
        """停止大模型提取"""
        if messagebox.askyesno("确认停止", "确定要停止当前提取任务吗?\n已处理的数据将不会保存。"):
            self.extract_stop_event.set()
            self.stop_extract_btn.config(state=tk.DISABLED)
            self.log("[提取] 用户请求停止提取...")
            self.extract_status.config(text="状态: 正在停止...", foreground="orange")

    def extract_worker(self, mid_json_paths: List[str], force_reextract: bool = False):
        """后台提取工作线程（支持单文件和批量模式）"""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)

            from extraction_pipeline import ExtractionPipeline

            custom_output_dir = self.extracted_json_output_dir.get().strip()
            if custom_output_dir:
                self.log(f"[提取] 使用自定义输出目录: {custom_output_dir}")
            else:
                self.log(f"[提取] 使用默认输出目录 (extraction_results)")

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

            for idx, mid_path in enumerate(mid_json_paths, 1):
                if self.extract_stop_event.is_set():
                    break
                self.root.after(0, lambda i=idx, t=total, p=mid_path: self.extract_status.config(
                    text=f"状态: 正在提取 ({i}/{t}): {Path(p).name}...", fg="blue"))

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

                self.log(f"[提取] 处理 {idx}/{total}: {Path(mid_path).name}")
                try:
                    out_path = pipeline.process_mid_json_sync(
                        mid_path,
                        progress_callback=lambda msg, p=None: progress_callback(msg, idx, total, p),
                        use_cache=not force_reextract,
                        extraction_mode=self._extraction_mode,
                    )
                    all_output_paths.append(out_path)
                    self.log(f"[提取] ✓ {Path(mid_path).name} -> {out_path}")
                except Exception as e:
                    self.log(f"[提取] ✗ {Path(mid_path).name} 失败: {e}")
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
        """更新提取进度（GUI线程调用）"""
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
        """提取完成回调(GUI线程调用)"""
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
        """批量提取完成回调(GUI线程调用)"""
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
        """批量提取部分失败回调(GUI线程调用)"""
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
        """提取被停止回调(GUI线程调用)"""
        self.extract_progress['value'] = 0
        self.extract_status.config(text="状态: 已停止", foreground="orange")
        self.extract_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_extract_btn.config(state=tk.DISABLED)
        self.log("[提取] ===== 大模型提取已停止 =====")
        self.log("[提取] 用户手动停止提取,结果未保存")

    def extraction_error(self, error_msg, traceback_text):
        """提取失败回调(GUI线程调用)"""
        self.extract_status.config(text="状态: 提取失败", foreground="red")
        self.extract_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)
        self.log("[提取] ===== 大模型提取流程失败 =====")
        self.log(f"[提取] 错误信息: {error_msg}")
        self.log(f"[提取] 详细堆栈:\n{traceback_text}")
        messagebox.showerror("提取错误", f"提取过程发生错误:\n{error_msg}")

    def view_result(self):
        """查看提取结果"""
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
        self.root.wait_window(dialog.top)

    def _select_result_file(self, paths: List[str]) -> Optional[str]:
        """弹出 Listbox 让用户选择要查看的结果文件"""
        top = tk.Toplevel(self.root)
        top.title("选择结果文件")
        top.geometry("500x350")
        top.transient(self.root)
        top.grab_set()

        result = [None]

        tk.Label(top, text="多个提取结果，请选择要查看的文件:").pack(pady=(10, 5))

        listbox = tk.Listbox(top, width=70, height=12)
        listbox.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        for p in paths:
            listbox.insert(tk.END, Path(p).name)

        def on_ok():
            sel = listbox.curselection()
            if sel:
                result[0] = paths[sel[0]]
            top.destroy()

        def on_cancel():
            top.destroy()

        btn_frame = tk.Frame(top)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="确定", command=on_ok, width=10).pack(side='left', padx=5)
        tk.Button(btn_frame, text="取消", command=on_cancel, width=10).pack(side='left', padx=5)

        listbox.focus_set()
        if paths:
            listbox.selection_set(0)
        top.wait_window()
        return result[0]

    def on_feedback_received(self, corrections):
        """接收人工修正反馈"""
        from rule_learner import RuleLearner
        rl = RuleLearner("rulebook.json")
        for field, new_val in corrections.items():
            rl.learn_from_correction(field, None, new_val)
        self.log(f"✓ 已记录 {len(corrections)} 条人工修正反馈")


class ResultReviewDialog:
    def __init__(self, parent, data, file_path, on_feedback=None):
        self.data = data
        self.file_path = file_path
        self.on_feedback = on_feedback
        self.corrections = {}

        self.top = tk.Toplevel(parent)
        self.top.title("提取结果审核")
        self.top.geometry("800x600")
        self.top.resizable(True, True)

        self.systems = self.data.get('nanozyme_systems', [])
        self.activities = self.data.get('catalytic_activities', [])
        self.figures = self.data.get('figures', [])
        self.evidence = self.data.get('evidence', [])
        self.legacy_fields = self.data.get('fields', {})

        self.current_system_idx = 0

        self.create_widgets()

    def create_widgets(self):
        meta = self.data.get('metadata', {})
        title_text = f"文献: {meta.get('title', '未知')[:50]}..."
        tk.Label(self.top, text=title_text, font=('Arial', 12, 'bold')).pack(pady=10)
        summary_text = (
            f"Schema: {meta.get('schema_version', 'legacy')} | "
            f"Nanozyme systems: {meta.get('systems_count', len(self.systems))} | "
            f"Catalytic activities: {meta.get('activities_count', len(self.activities))} | "
            f"Evidence: {meta.get('evidence_count', len(self.evidence))}"
        )
        tk.Label(self.top, text=summary_text, fg="gray").pack(pady=(0, 8))

        if len(self.systems) > 1:
            switch_frame = tk.Frame(self.top)
            switch_frame.pack(fill="x", padx=10, pady=5)
            tk.Label(switch_frame, text="系统选择:").pack(side="left")
            self.system_var = tk.StringVar()
            system_names = [s.get('system_name', f"System {i+1}") for i, s in enumerate(self.systems)]
            self.system_dropdown = ttk.Combobox(switch_frame, textvariable=self.system_var, values=system_names, state="readonly", width=30)
            self.system_dropdown.pack(side="left", padx=5)
            self.system_dropdown.current(0)
            self.system_dropdown.bind("<<ComboboxSelected>>", self._on_system_change)
            tk.Label(switch_frame, text="（切换以审核不同纳米酶系统）", fg="gray").pack(side="left", padx=5)

        self.notebook = ttk.Notebook(self.top)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)

        self.legacy_tab = ttk.Frame(self.notebook)
        self.system_tab = ttk.Frame(self.notebook)
        self.activity_tab = ttk.Frame(self.notebook)
        self.figure_tab = ttk.Frame(self.notebook)
        self.evidence_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.legacy_tab, text="Legacy 投影")
        self.notebook.add(self.system_tab, text="纳米酶系统")
        self.notebook.add(self.activity_tab, text="催化活性")
        self.notebook.add(self.figure_tab, text="图表分析")
        self.notebook.add(self.evidence_tab, text="证据池")

        self.entries = {}
        self._build_legacy_tab()
        self._build_system_tab()
        self._build_activity_tab()
        self._build_figure_tab()
        self._build_evidence_tab()

        btn_frame = tk.Frame(self.top)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="保存修正", command=self.save_feedback, bg="lightblue").pack(side="left", padx=10)
        tk.Button(btn_frame, text="仅关闭", command=self.top.destroy).pack(side="left", padx=10)

    def _on_system_change(self, event=None):
        idx = self.system_dropdown.current()
        self.current_system_idx = idx
        self._rebuild_system_tab()

    def _build_legacy_tab(self):
        for w in self.legacy_tab.winfo_children():
            w.destroy()
        self.entries = {}
        frame = self._make_scrollable(self.legacy_tab)
        row = 0
        for field_name, info in self.legacy_fields.items():
            value = info.get('value', '')
            conf = info.get('confidence', 0)
            needs_review = info.get('needs_review', False)
            fg_color = "red" if needs_review else "black"
            label_text = f"{field_name} (置信度: {conf:.2f})" + (" [需要审核]" if needs_review else "")
            tk.Label(frame, text=label_text, fg=fg_color, anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(value) if value is not None else "")
            entry = tk.Entry(frame, textvariable=var, width=50)
            entry.grid(row=row, column=1, padx=5, pady=2)
            if needs_review:
                entry.config(bg="#fff0f0")
            self.entries[field_name] = var
            row += 1

    def _build_system_tab(self):
        for w in self.system_tab.winfo_children():
            w.destroy()
        frame = self._make_scrollable(self.system_tab)
        if not self.systems:
            tk.Label(frame, text="无纳米酶系统提取结果").pack(pady=20)
            return
        sys_data = self.systems[self.current_system_idx]
        row = 0
        for key, val in sys_data.items():
            tk.Label(frame, text=key, anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            display_val = str(val) if isinstance(val, list) else str(val)
            tk.Label(frame, text=display_val[:150], anchor="w", wraplength=500, justify="left").grid(row=row, column=1, padx=5, pady=2, sticky="w")
            row += 1

    def _rebuild_system_tab(self):
        self._build_system_tab()

    def _build_activity_tab(self):
        for w in self.activity_tab.winfo_children():
            w.destroy()
        frame = self._make_scrollable(self.activity_tab)
        if not self.activities:
            tk.Label(frame, text="无催化活性提取结果").pack(pady=20)
            return
        row = 0
        for act in self.activities:
            tk.Label(frame, text=f"--- {act.get('activity_id', 'N/A')} ---", font=('Arial', 10, 'bold')).grid(row=row, column=0, columnspan=2, sticky="w", pady=5)
            row += 1
            for key, val in act.items():
                tk.Label(frame, text=key, anchor="w").grid(row=row, column=0, sticky="w", pady=1)
                tk.Label(frame, text=str(val)[:120], anchor="w", wraplength=500, justify="left").grid(row=row, column=1, padx=5, pady=1, sticky="w")
                row += 1

    def _build_figure_tab(self):
        for w in self.figure_tab.winfo_children():
            w.destroy()
        frame = self._make_scrollable(self.figure_tab)
        if not self.figures:
            tk.Label(frame, text="无图表分析结果").pack(pady=20)
            return
        row = 0
        for fig in self.figures:
            tk.Label(frame, text=f"--- {fig.get('figure_id', 'N/A')} (page={fig.get('page')}) ---", font=('Arial', 10, 'bold')).grid(row=row, column=0, columnspan=2, sticky="w", pady=5)
            row += 1
            for key, val in fig.items():
                if key == 'extracted_values' or key == 'observations':
                    tk.Label(frame, text=key, anchor="w").grid(row=row, column=0, sticky="w", pady=1)
                    tk.Label(frame, text=str(val)[:120], anchor="w", wraplength=500, justify="left").grid(row=row, column=1, padx=5, pady=1, sticky="w")
                    row += 1

    def _build_evidence_tab(self):
        for w in self.evidence_tab.winfo_children():
            w.destroy()
        frame = self._make_scrollable(self.evidence_tab)
        if not self.evidence:
            tk.Label(frame, text="无证据记录").pack(pady=20)
            return
        row = 0
        for ev in self.evidence:
            tk.Label(frame, text=f"[{ev.get('source_kind', '?')}] {ev.get('evidence_id', 'N/A')}", font=('Arial', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
            row += 1
            quote = ev.get('text_quote', '')
            tk.Label(frame, text=quote[:200], anchor="w", wraplength=600, justify="left").grid(row=row, column=0, columnspan=2, sticky="w", padx=10)
            row += 1

    @staticmethod
    def _make_scrollable(parent):
        frame_outer = tk.Frame(parent)
        frame_outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(frame_outer)
        scrollbar = ttk.Scrollbar(frame_outer, orient="vertical", command=canvas.yview)
        frame_inner = ttk.Frame(canvas)
        frame_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return frame_inner

    def save_feedback(self):
        original_fields = self.data.get('fields', {})
        for field_name, var in self.entries.items():
            new_val_str = var.get().strip()
            if new_val_str == "":
                new_val = None
            else:
                if new_val_str.replace('.', '', 1).isdigit():
                    new_val = float(new_val_str) if '.' in new_val_str else int(new_val_str)
                else:
                    new_val = new_val_str
            original_val = original_fields.get(field_name, {}).get('value')
            if new_val != original_val:
                self.corrections[field_name] = new_val
        if self.corrections and self.on_feedback:
            self.on_feedback(self.corrections)
            messagebox.showinfo("反馈已记录", f"已记录 {len(self.corrections)} 个字段的修正")
        self.top.destroy()


if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = PDFBasicGUI(root)
        root.mainloop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")
