import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import asyncio
import json
import os
import re
import time
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


@dataclass
class FileState:
    path: str
    stem: str = ""
    phase: str = "pending"
    error: str = ""
    result: Optional[Dict] = None
    start_time: float = 0.0
    end_time: float = 0.0

    def __post_init__(self):
        if not self.stem:
            self.stem = Path(self.path).stem


class NanozymeApp:
    PHASES = ["pending", "parsing", "preprocessing", "extracting", "done", "error"]
    PHASE_LABELS = {
        "pending": "等待", "parsing": "解析", "preprocessing": "预处理",
        "extracting": "提取", "done": "完成", "error": "错误"
    }
    PHASE_COLORS = {
        "pending": "#9E9E9E", "parsing": "#FF9800", "preprocessing": "#2196F3",
        "extracting": "#9C27B0", "done": "#4CAF50", "error": "#F44336"
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NanozymeExtractor — 纳米酶文献智能提取系统")
        self.root.geometry("1280x820")
        self.root.minsize(1024, 700)

        self.files: List[FileState] = []
        self.stop_event = threading.Event()
        self.extract_stop_event = threading.Event()
        self.server_process = None
        self.server_ready = False
        self._log_queue = []
        self._running = False

        self._setup_styles()
        self._build_ui()
        self._setup_logging()
        self._load_config()

    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        self.style.configure("Subtitle.TLabel", font=("Microsoft YaHei UI", 11))
        self.style.configure("Phase.TLabel", font=("Microsoft YaHei UI", 9))
        self.style.configure("Big.TButton", font=("Microsoft YaHei UI", 12, "bold"), padding=10)
        self.style.configure("Run.TButton", font=("Microsoft YaHei UI", 13, "bold"), padding=14)
        self.style.configure("Field.TLabel", font=("Microsoft YaHei UI", 9), foreground="#555")
        self.style.configure("Value.TLabel", font=("Microsoft YaHei UI", 10, "bold"))
        self.style.configure("Card.TFrame", relief="groove", borderwidth=1)
        self.style.configure("Status.TLabel", font=("Microsoft YaHei UI", 9))

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(main)
        top.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(top, text="🧬 纳米酶文献智能提取", style="Title.TLabel").pack(side=tk.LEFT)
        self.status_label = ttk.Label(top, text="就绪", style="Subtitle.TLabel", foreground="#666")
        self.status_label.pack(side=tk.RIGHT)

        body = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(body, width=380)
        body.add(left, weight=1)

        right = ttk.Frame(body)
        body.add(right, weight=2)

        self._build_left(left)
        self._build_right(right)

        bottom = ttk.Frame(main)
        bottom.pack(fill=tk.X, pady=(6, 0))
        self.progress = ttk.Progressbar(bottom, mode="determinate", length=400)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.progress_label = ttk.Label(bottom, text="", style="Status.TLabel")
        self.progress_label.pack(side=tk.LEFT)
        self.time_label = ttk.Label(bottom, text="", style="Status.TLabel")
        self.time_label.pack(side=tk.RIGHT)

    def _build_left(self, parent):
        input_frame = ttk.LabelFrame(parent, text="📁 输入", padding=8)
        input_frame.pack(fill=tk.X, pady=(0, 6))

        btn_row = ttk.Frame(input_frame)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="选择PDF文件", command=self._select_files).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="选择文件夹", command=self._select_folder).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="清空", command=self._clear_files).pack(side=tk.LEFT)

        self.file_count_label = ttk.Label(input_frame, text="未选择文件", style="Field.TLabel")
        self.file_count_label.pack(anchor=tk.W, pady=(4, 0))

        list_frame = ttk.Frame(input_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        cols = ("file", "phase")
        self.file_tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=8, selectmode="browse")
        self.file_tree.heading("file", text="文件")
        self.file_tree.heading("phase", text="状态")
        self.file_tree.column("file", width=260, minwidth=180)
        self.file_tree.column("phase", width=60, minwidth=50)
        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=vsb.set)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_tree.bind("<<TreeviewSelect>>", self._on_file_select)

        config_frame = ttk.LabelFrame(parent, text="⚙️ 配置", padding=8)
        config_frame.pack(fill=tk.X, pady=(0, 6))

        mode_row = ttk.Frame(config_frame)
        mode_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(mode_row, text="提取模式:", style="Field.TLabel").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="single_main_nanozyme")
        ttk.Radiobutton(mode_row, text="单主纳米酶", variable=self.mode_var, value="single_main_nanozyme").pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(mode_row, text="多系统全量", variable=self.mode_var, value="canonical_multi_system").pack(side=tk.LEFT)

        api_row = ttk.Frame(config_frame)
        api_row.pack(fill=tk.X, pady=(0, 4))
        self.llm_var = tk.BooleanVar(value=True)
        self.vlm_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(api_row, text="LLM增强", variable=self.llm_var).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(api_row, text="VLM增强", variable=self.vlm_var).pack(side=tk.LEFT)
        ttk.Button(api_row, text="测试连接", command=self._test_connection).pack(side=tk.RIGHT)

        self.api_status_label = ttk.Label(config_frame, text="", style="Field.TLabel")
        self.api_status_label.pack(anchor=tk.W)

        run_frame = ttk.Frame(parent)
        run_frame.pack(fill=tk.X, pady=(0, 6))
        self.run_btn = ttk.Button(run_frame, text="▶ 一键提取", style="Run.TButton", command=self._start_pipeline)
        self.run_btn.pack(fill=tk.X, pady=(0, 4))
        self.stop_btn = ttk.Button(run_frame, text="⏹ 停止", state=tk.DISABLED, command=self._stop_pipeline)
        self.stop_btn.pack(fill=tk.X)

        stats_frame = ttk.LabelFrame(parent, text="📊 批量统计", padding=8)
        stats_frame.pack(fill=tk.X)
        self.stats_text = tk.Text(stats_frame, height=6, font=("Consolas", 9), state=tk.DISABLED, wrap=tk.WORD, bg="#FAFAFA")
        self.stats_text.pack(fill=tk.BOTH)

    def _build_right(self, parent):
        nb = ttk.Notebook(parent)
        nb.pack(fill=tk.BOTH, expand=True)

        result_tab = ttk.Frame(nb, padding=8)
        nb.add(result_tab, text="📋 提取结果")
        self._build_result_tab(result_tab)

        log_tab = ttk.Frame(nb, padding=8)
        nb.add(log_tab, text="📝 运行日志")
        self._build_log_tab(log_tab)

        self.notebook = nb

    def _build_result_tab(self, parent):
        if not hasattr(self, '_result_widgets'):
            self._result_widgets = {}

        top_bar = ttk.Frame(parent)
        top_bar.pack(fill=tk.X, pady=(0, 6))
        self.result_title_label = ttk.Label(top_bar, text="选择左侧文件查看结果", style="Subtitle.TLabel")
        self.result_title_label.pack(side=tk.LEFT)
        ttk.Button(top_bar, text="保存JSON", command=self._save_result).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(top_bar, text="打开文件夹", command=self._open_result_dir).pack(side=tk.RIGHT)

        canvas_frame = ttk.Frame(parent)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, bg="#FAFAFA", highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        self.result_inner = ttk.Frame(canvas)
        self.result_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.result_inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._result_canvas = canvas

        self._build_result_cards(self.result_inner)

    def _build_result_cards(self, parent):
        self._cards = {}

        card_data = [
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

        for card_id, card_title, fields in card_data:
            card = ttk.LabelFrame(parent, text=card_title, padding=8, style="Card.TFrame")
            card.pack(fill=tk.X, pady=(0, 8), padx=4)

            grid = ttk.Frame(card)
            grid.pack(fill=tk.X)
            grid.columnconfigure(1, weight=1)

            self._cards[card_id] = {}
            for i, (fid, flabel) in enumerate(fields):
                ttk.Label(grid, text=flabel, style="Field.TLabel").grid(row=i, column=0, sticky=tk.W, pady=2, padx=(0, 8))
                val_label = ttk.Label(grid, text="—", style="Value.TLabel", wraplength=500)
                val_label.grid(row=i, column=1, sticky=tk.W, pady=2)
                self._cards[card_id][fid] = val_label

        diag_card = ttk.LabelFrame(parent, text="📈 诊断信息", padding=8, style="Card.TFrame")
        diag_card.pack(fill=tk.X, pady=(0, 8), padx=4)
        self.diag_text = tk.Text(diag_card, height=5, font=("Consolas", 9), state=tk.DISABLED, wrap=tk.WORD, bg="#FAFAFA")
        self.diag_text.pack(fill=tk.BOTH)

    def _build_log_tab(self, parent):
        self.log_text = tk.Text(parent, font=("Consolas", 9), state=tk.DISABLED, wrap=tk.WORD)
        log_vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_vsb.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text.tag_configure("INFO", foreground="#333")
        self.log_text.tag_configure("WARNING", foreground="#FF8F00")
        self.log_text.tag_configure("ERROR", foreground="#D32F2F")
        self.log_text.tag_configure("SUCCESS", foreground="#2E7D32")

    def _setup_logging(self):
        handler = _GUILogHandler(self)
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)

    def _load_config(self):
        try:
            from config_manager import ConfigManager
            cm = ConfigManager()
            llm_cfg = cm.get_llm_config()
            vlm_cfg = cm.get_vlm_config()
            llm_ok = bool(llm_cfg.api_key and llm_cfg.base_url)
            vlm_ok = bool(vlm_cfg.api_key and vlm_cfg.base_url)
            self.api_status_label.config(text=f"LLM: {'✓' if llm_ok else '✗'}  VLM: {'✓' if vlm_ok else '✗'}")
        except Exception:
            self.api_status_label.config(text="配置加载失败")

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
            phase_text = self.PHASE_LABELS.get(f.phase, f.phase)
            self.file_tree.insert("", tk.END, iid=str(i), values=(f.stem, phase_text))
        n = len(self.files)
        self.file_count_label.config(text=f"已选择 {n} 个文件" if n else "未选择文件")

    def _update_file_phase(self, idx: int, phase: str, error: str = ""):
        if 0 <= idx < len(self.files):
            self.files[idx].phase = phase
            self.files[idx].error = error
            phase_text = self.PHASE_LABELS.get(phase, phase)
            if error:
                phase_text = "错误"
            try:
                self.file_tree.item(str(idx), values=(self.files[idx].stem, phase_text))
            except tk.TclError:
                pass

    def _on_file_select(self, event):
        sel = self.file_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.files):
            self._display_result(self.files[idx])

    def _display_result(self, fstate: FileState):
        if fstate.result is None:
            self.result_title_label.config(text=f"{fstate.stem} — 尚无结果")
            self._clear_result_display()
            return

        r = fstate.result
        sel = r.get("selected_nanozyme", {})
        act = r.get("main_activity", {})
        kin = act.get("kinetics", {})
        ph = act.get("pH_profile", {})
        temp = act.get("temperature_profile", {})
        apps = r.get("applications", [])

        self.result_title_label.config(text=f"{fstate.stem}")

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

        diag = r.get("diagnostics", {})
        self.diag_text.config(state=tk.NORMAL)
        self.diag_text.delete("1.0", tk.END)
        if diag:
            conf = diag.get("overall_confidence", "—")
            warns = diag.get("warnings", [])
            self.diag_text.insert(tk.END, f"置信度: {conf}\n")
            if warns:
                self.diag_text.insert(tk.END, f"警告 ({len(warns)}):\n")
                for w in warns[:8]:
                    self.diag_text.insert(tk.END, f"  • {w}\n")
            else:
                self.diag_text.insert(tk.END, "无警告\n")
        else:
            self.diag_text.insert(tk.END, "无诊断信息\n")
        self.diag_text.config(state=tk.DISABLED)

    def _set_card(self, card_id: str, field_id: str, value):
        if card_id in self._cards and field_id in self._cards[card_id]:
            v = str(value) if value is not None else "—"
            self._cards[card_id][field_id].config(text=v)

    def _clear_result_display(self):
        for card_id, fields in self._cards.items():
            for fid, label in fields.items():
                label.config(text="—")
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

    def _test_connection(self):
        self.api_status_label.config(text="测试中...")
        threading.Thread(target=self._test_connection_worker, daemon=True).start()

    def _test_connection_worker(self):
        try:
            from api_client import APIClient
            from config_manager import ConfigManager
            cm = ConfigManager()
            client = APIClient(cm)
            loop = asyncio.new_event_loop()
            try:
                llm_result = loop.run_until_complete(client.test_connection("text"))
                vlm_result = loop.run_until_complete(client.test_connection("vision"))
                llm_ok = llm_result.get("success", False)
                vlm_ok = vlm_result.get("success", False)
                self.root.after(0, lambda: self.api_status_label.config(
                    text=f"LLM: {'✓' if llm_ok else '✗'}  VLM: {'✓' if vlm_ok else '✗'}"
                ))
            finally:
                loop.close()
        except Exception as e:
            self.root.after(0, lambda: self.api_status_label.config(text=f"测试失败: {e}"))

    def _start_pipeline(self):
        if not self.files:
            messagebox.showwarning("提示", "请先选择PDF文件")
            return
        if self._running:
            return
        self._running = True
        self.stop_event.clear()
        self.extract_stop_event.clear()
        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_label.config(text="运行中...")
        self._start_time = time.time()

        for f in self.files:
            f.phase = "pending"
            f.error = ""
            f.result = None
        self._refresh_file_tree()

        threading.Thread(target=self._pipeline_worker, daemon=True).start()

    def _stop_pipeline(self):
        self.stop_event.set()
        self.extract_stop_event.set()
        self.status_label.config(text="正在停止...")

    def _pipeline_worker(self):
        try:
            self._pipeline_run()
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            self.root.after(0, lambda: self.status_label.config(text=f"错误: {e}"))
        finally:
            self._running = False
            self.root.after(0, lambda: self.run_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))
            self._update_stats()

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
                pdf_json = self._parse_pdf(fstate.path, output_dir)
                if pdf_json is None:
                    self._update_file_phase(i, "error", "PDF解析失败")
                    continue

                if self.stop_event.is_set():
                    break

                self.root.after(0, lambda idx=i: self._update_progress(idx, total, "预处理"))
                self._update_file_phase(i, "preprocessing")
                mid_task = self._preprocess(pdf_json, fstate.path, output_dir)
                if mid_task is None:
                    self._update_file_phase(i, "error", "预处理失败")
                    continue

                if self.stop_event.is_set():
                    break

                self.root.after(0, lambda idx=i: self._update_progress(idx, total, "提取"))
                self._update_file_phase(i, "extracting")
                result = self._extract(mid_task, output_dir, fstate.stem)

                fstate.end_time = time.time()
                if result is not None:
                    fstate.result = result
                    self._update_file_phase(i, "done")
                    self._save_extracted(result, output_dir, fstate.stem)
                else:
                    self._update_file_phase(i, "error", "提取失败")

            except Exception as e:
                fstate.end_time = time.time()
                self._update_file_phase(i, "error", str(e))
                logger.error(f"[{fstate.stem}] Error: {e}")

            self.root.after(0, lambda idx=i: self._update_progress(idx + 1, total, ""))

        elapsed = time.time() - self._start_time
        self.root.after(0, lambda: self.status_label.config(
            text=f"完成 ({elapsed:.1f}s)" if not self.stop_event.is_set() else "已停止"
        ))

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
        except Exception as e:
            logger.error(f"Preprocess error: {e}")
            return None

    def _extract(self, mid_task_path: str, output_dir: str, stem: str) -> Optional[Dict]:
        try:
            from extraction_pipeline import ExtractionPipeline
            from config_manager import ConfigManager
            cm = ConfigManager()
            mode = self.mode_var.get()
            enable_llm = self.llm_var.get()
            enable_vlm = self.vlm_var.get()

            pipeline = ExtractionPipeline(cm, mode=mode)
            loop = asyncio.new_event_loop()
            try:
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
        if hasattr(self, '_start_time'):
            elapsed = time.time() - self._start_time
            self.time_label.config(text=f"耗时 {elapsed:.1f}s")

    def _update_stats(self):
        total = len(self.files)
        done = sum(1 for f in self.files if f.phase == "done")
        errors = sum(1 for f in self.files if f.phase == "error")
        pending = total - done - errors

        km_count = 0
        vmax_count = 0
        ph_count = 0
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

        done_with_result = max(done, 1)
        lines = [
            f"完成: {done}/{total}  错误: {errors}  待处理: {pending}",
            f"Km提取率: {km_count}/{done} = {km_count/done_with_result*100:.0f}%",
            f"Vmax提取率: {vmax_count}/{done} = {vmax_count/done_with_result*100:.0f}%",
            f"最适pH提取率: {ph_count}/{done} = {ph_count/done_with_result*100:.0f}%",
        ]
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete("1.0", tk.END)
        self.stats_text.insert(tk.END, "\n".join(lines))
        self.stats_text.config(state=tk.DISABLED)

    def _save_result(self):
        sel = self.file_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个文件")
            return
        idx = int(sel[0])
        fstate = self.files[idx]
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
        tag = level if level in ("INFO", "WARNING", "ERROR") else "INFO"
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)


class _GUILogHandler(logging.Handler):
    def __init__(self, app: NanozymeApp):
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            level = record.levelname
            self.app.root.after(0, lambda: self.app.append_log(level, msg))
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = NanozymeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
