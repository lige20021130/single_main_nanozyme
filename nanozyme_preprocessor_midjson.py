# nanozyme_preprocessor_midjson.py - 高质量纳米酶信息筛选器
VERSION = "nanozyme.v1.2"
"""
功能：
1. 从PDF解析JSON中提取所有文本（段落、标题、图注）
2. 按句子拆分，计算每个句子的“纳米酶信息密度分数”
3. 根据分数筛选高价值句子，保留章节多样性
4. 输出单一精炼文本，供LLM一次性提取
5. 支持从 rulebook.json 加载规则（关键词权重、阈值等）
6. 图像处理保持不变
"""

import json
import re
import shutil
import os
import math
import time
from copy import deepcopy
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from collections import defaultdict
from dataclasses import dataclass, field
import logging

from config_manager import ConfigManager
from nanozyme_models import ENZYME_REGISTRY, get_all_substrate_keywords, get_all_enzyme_keywords, get_enzyme_type_enum_string, get_assay_type_enum_string, get_application_type_enum_string, EnzymeType

logger = logging.getLogger(__name__)

# ========== 配置（可从外部 config.yaml 覆盖） ==========
DEFAULT_CONFIG = {
    "min_sentence_length": 15,
    "max_sentence_length": 500,
    "min_priority_floor": -4.0,
    "min_sentences_per_section": {
        "abstract": 3,
        "introduction": 2,
        "experimental": 2,
        "results": 3,
        "conclusion": 2,
        "unknown": 1
    },
    "section_boost": {
        "abstract": 1.5,
        "introduction": 1.0,
        "experimental": 1.2,
        "results": 1.3,
        "results_like": 1.25,
        "conclusion": 1.2,
        "unknown": 0.8
    },
    "keyword_weights": {
        "nanozyme": 5.0,
        "Km": 8.0,
        "Vmax": 8.0,
        "kcat": 7.0,
        "michaelis": 6.0,
        "menten": 6.0,
        "peroxidase-like": 5.0,
        "oxidase-like": 5.0,
        "catalase-like": 5.0,
        "catechol oxidase-like": 5.0,
        "catalytic activity": 4.0,
        "kinetic": 4.0,
        "substrate": 3.0,
        "TMB": 3.0,
        "ABTS": 3.0,
        "OPD": 3.0,
        "H2O2": 3.0,
        "TEM": 2.0,
        "HRTEM": 2.0,
        "HAADF-STEM": 2.0,
        "EELS": 2.0,
        "EDS mapping": 2.0,
        "XRD": 2.0,
        "XPS": 2.0,
        "XAFS": 3.0,
        "XANES": 3.0,
        "EXAFS": 3.0,
        "SAED": 2.0,
        "EDX": 2.0,
        "STEM": 2.0,
        "FT-IR": 2.0,
        "UV-vis": 2.0,
        "Raman": 2.0,
        "SERS": 2.0,
        "nanotube": 3.0,
        "nanoparticle": 3.0,
        "nanosheet": 3.0,
        "oxygen vacancy": 4.0,
        "single-atom": 4.0,
        "active site": 4.0,
        "ROS": 4.0,
        "radical": 3.0,
        "mechanism": 4.0,
        "specificity": 3.0,
        "comparison": 2.0,
        "superior": 3.0,
        "therapy": 3.0,
        "sensing": 3.0,
        "detection limit": 3.0,
        "linear range": 3.0,
        "defect": 3.0,
        "numeric_with_unit": 3.0,
        "range": 2.0,
        "antibacterial": 3.0,
        "wound healing": 3.0,
        "antioxidant": 3.0,
        "bioimaging": 2.5,
        "LOD": 4.0,
        "biocompatibility": 3.0,
        "cytoprotection": 3.0,
        "ROS scavenging": 3.0,
        "synthesis": 2.0,
        "hydrothermal": 2.0,
        "coprecipitation": 2.0,
        "sol-gel": 2.0,
        "particle size": 2.5,
        "surface modification": 2.0,
        "food safety": 2.5,
        "anti-inflammatory": 3.0,
        "water treatment": 2.5,
        "heavy metal": 2.5,
    },
    "remove_patterns": [
        r"(?i)references?$",
        r"(?i)acknowledg(e|i)ments?$",
        r"(?i)author\s+information",
        r"(?i)supplementary\s+(information|material)",
        r"(?i)conflict\s+of\s+interest",
        r"(?i)funding",
        r"https?://\S+",
        r"©\s+\d{4}",
        r"(?i)^accepted\s+manuscript$",
        r"(?i)^just\s+accepted$",
        r"(?i)^this\s+(article|paper)\s+is\s+©",
        r"(?i)^angew\.\s*chem\.\s*(int\.\s*ed\.)?$",
        r"(?i)^wiley\s+online\s+library$",
        r"(?i)^manuscript$",
        r"(?i)^draft$",
        r"(?i)^corrected\s+proof$",
        r"(?i)^springer\s+nature$",
        r"(?i)^royal\s+society\s+of\s+chemistry$",
        r"(?i)^american\s+chemical\s+society$",
        r"(?i)^taylor\s*&\s*francis$",
    ],
    "section_patterns": {
        "abstract": r"(?i)^abstract\b",
        "introduction": r"(?i)^1\.?\s*introduction\b",
        "experimental": r"(?i)^2\.?\s*(experimental|materials and methods)",
        "results": r"(?i)^3\.?\s*(results|results and discussion)",
        "conclusion": r"(?i)^4\.?\s*conclusion\b",
    },
    "image_filter": {
        "min_file_size_kb": 10,
        "min_dimension": 50,
        "min_dimension_with_caption": 30,
        "uncaptioned_min_both": 200,
        "require_caption_for_small": True,
        "allow_uncaptioned_in_supplementary": False,
        "max_images_main": 8,
        "max_images_supplementary": 6,
    },
    "caption_patterns": {
        "sfig": [
            r"^(?:supplementary\s+figure|supplementary\s+fig\.?)\s*S?(\d+)\b",
            r"^(?:figure|fig\.?)\s*S(\d+)\b",
        ],
        "scheme": [
            r"^scheme\s+(\d+)\b",
        ],
        "fig": [
            r"^(?:figure|fig\.?)\s+(\d+)\b",
        ],
    },
    "adaptive_chunking": {
        "enabled": False,
        "prefer_single_chunk_below_chars": 8000,
        "prefer_single_chunk_below_sentences": 40,
        "multi_chunk_min_system_mentions": 3,
        "multi_chunk_on_multi_assay": True,
        "max_chars_per_chunk": 6000
    },
    "text_budget": {
        "target_sentences": 42,
        "target_chars": 9000,
        "hard_max_sentences": 55,
        "hard_max_chars": 12000,
        "section_caps": {
            "results": 28,
            "results_like": 18,
            "experimental": 12,
            "conclusion": 3,
            "introduction": 3,
            "abstract": 2,
            "unknown": 4,
            "metadata": 1,
            "backmatter": 1,
        },
    },
    # ========== supplementary_atlas 专用配置 ==========
    "supplementary_atlas": {
        # TOC页检测：前N页内出现目录特征即标记
        "toc_detection_page_range": 3,
        # TOC条目阈值：单页内超过此数量则判定为TOC页
        "toc_entry_threshold": 4,
        # atlas文本优先级映射
        "priority_levels": {
            "activity_result_caption": "high",
            "kinetics_caption": "high",
            "comparison_caption": "high",
            "mechanism_caption": "high",
            "table_parameter_rows": "high",
            "supplementary_notes": "high",
            "methods_summary": "medium",
            "synthesis_summary": "medium",
            "structure_explainer": "medium",
            "pure_morphology_captions": "low",
            "repetitive_sem_caption": "low",
            "reference_pages": "low",
        },
        # atlas升权关键词
        "atlas_high_value_signals": [
            r"(?i)\bperoxidase-like activity\b",
            r"(?i)\bkinetic curves?\b",
            r"(?i)\bMichaelis-Menten\b",
            r"(?i)\beg occupancy\b",
            r"(?i)\boxidation state\b",
            r"(?i)\boxygen vacancy\b",
            r"(?i)\bcovalency\b",
            r"(?i)\badsorption energy\b",
            r"(?i)\bcomparison with literature\b",
            r"(?i)\brepresentative nanozymes?\b",
            r"(?i)\bKm\b",
            r"(?i)\bVmax\b",
            r"(?i)\bkcat\b",
        ],
        # atlas预算配置
        "atlas_budget": {
            "target_sentences": 60,
            "target_chars": 12000,
            "hard_max_sentences": 80,
            "hard_max_chars": 16000,
            "high_priority_min": 15,
            "medium_priority_min": 8,
        },
        # 纯形态学图注降权阈值
        "morphology_caption_max_keep": 3,
        # 表格最小字数阈值
        "table_min_chars": 50,
    },
}


def _deep_update(dst: Dict[str, Any], src: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    for key, value in (src or {}).items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_update(dst[key], value)
        else:
            dst[key] = deepcopy(value)
    return dst


@dataclass
class BlockInfo:
    block_id: str
    page: int
    section: str
    kind: str
    kid_ids: List[int]
    bbox: Optional[List[float]]
    text: str


@dataclass
class FigureInfo:
    figure_id: str
    page: int
    image_kid_id: int
    bbox: Optional[List[float]]
    image_path: str
    caption_kid_ids: List[int]
    caption_text: str


@dataclass
class SentenceInfo:
    """句子信息"""
    sentence_id: str
    text: str
    section: str
    page: int
    score: float
    contains_numeric: bool
    contains_keyword: bool
    kid_ids: List[int] = field(default_factory=list)
    bbox: Optional[List[float]] = None
    source_kind: str = "text"
    value_tags: List[str] = field(default_factory=list)
    normalized_text: str = ""
    hard_recall: bool = False
    hard_recall_patterns: List[str] = field(default_factory=list)
    block_id: Optional[str] = None
    contains_kinetics_signal: bool = False
    contains_material_signal: bool = False
    signal_type: str = ""
    candidate_enzyme_mentions: List[str] = field(default_factory=list)
    candidate_substrate_mentions: List[str] = field(default_factory=list)
    candidate_application_mentions: List[str] = field(default_factory=list)
    figure_label: Optional[str] = None


def _filter_candidate_mentions(mentions: List[str], context_text: str = "") -> Tuple[List[str], Dict[str, Any]]:
    try:
        from quality_gates import filter_candidate_system_mentions
        return filter_candidate_system_mentions(mentions, context_text)
    except ImportError:
        return mentions, {"total_input": len(mentions), "kept": len(mentions), "filtered": 0, "filtered_items": []}


class NanozymePreprocessor:
    """高质量纳米酶信息筛选器"""

    def __init__(self, json_path: str, images_root: Optional[str] = None,
                 output_root: Optional[str] = None, rulebook_path: str = "rulebook.json",
                 runtime_overrides: Optional[Dict[str, Any]] = None,
                 pdf_stem: Optional[str] = None,
                 extraction_mode: Optional[str] = None):
        self.json_path = Path(json_path)
        self.images_root = Path(images_root) if images_root else self.json_path.parent
        self.output_root = Path(output_root) if output_root else self.json_path.parent
        self.pdf_stem = pdf_stem or self.json_path.stem
        self.high_value_dir = self.output_root / "high_value_images" / self.pdf_stem
        self.high_value_dir.mkdir(parents=True, exist_ok=True)

        self.extraction_mode = extraction_mode or "single_main_nanozyme"

        # 加载规则库
        self.rulebook_path = Path(rulebook_path)
        self.rulebook = self._load_rulebook()

        # 合并配置（规则库中的配置优先）
        self.runtime_overrides = runtime_overrides or {}
        self.config = self._load_effective_config()

        with open(json_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        self.kids = self.data.get('kids', [])

        self.images: List[Dict] = []
        self.renamed_count = 0

        # 存储处理后的精炼文本
        self.refined_text = ""
        self.sentences: List[SentenceInfo] = []
        self.blocks: List[Dict[str, Any]] = []
        self.figures: List[FigureInfo] = []
        self.chunks: List[str] = []
        self.chunk_contexts: List[Dict[str, Any]] = []
        self.figure_ocr_sentences: List[SentenceInfo] = []
        self.paper_metadata: Dict[str, Any] = {}
        self.chunk_sentence_groups: List[List[SentenceInfo]] = []
        self.document_kind = "main"
        self.is_atlas = False
        self.normalized_images: List[Dict[str, Any]] = []
        self.normalized_captions: List[Dict[str, Any]] = []
        self.image_key_source_stats: Dict[str, int] = defaultdict(int)
        self.caption_match_stats: Dict[str, Any] = {}
        self._caption_match_page_stats: List[Dict[str, Any]] = []
        self.diagnostics: Dict[str, Any] = {
            "image_key_sources": {},
            "caption_match": {},
            "dropped_text_reasons": {},
            "chunk_stats": {},
            "duplicate_output_filenames": [],
            "selection": {},
        }

    def reload_rules(self) -> None:
        """热重载规则库，使最新权重生效。"""
        self.rulebook = self._load_rulebook()
        self.config = self._load_effective_config()
        logger.info("规则库已热重载")

    # ---------- 规则库加载与配置合并 ----------
    def _load_rulebook(self) -> Dict:
        if self.rulebook_path.exists():
            try:
                with open(self.rulebook_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载规则库失败: {e}")
        return {}

    def _load_effective_config(self) -> Dict[str, Any]:
        config = deepcopy(DEFAULT_CONFIG)

        try:
            config_manager = ConfigManager.get_instance()
            pp_config = config_manager.get("preprocessor_config", {})
            if hasattr(pp_config, "to_dict"):
                pp_config = pp_config.to_dict()
            _deep_update(config, pp_config)
            image_filter_config = config_manager.get("image_filter", {})
            if hasattr(image_filter_config, "to_dict"):
                image_filter_config = image_filter_config.to_dict()
            _deep_update(config, {"image_filter": image_filter_config})
        except Exception as exc:
            logger.info(f"ConfigManager 不可用，回退到默认配置: {exc}")

        _deep_update(config, self.rulebook.get("preprocessor_config", {}))
        if "keyword_weights" in self.rulebook:
            _deep_update(config, {"keyword_weights": self.rulebook["keyword_weights"]})
        if self.runtime_overrides:
            _deep_update(config, self.runtime_overrides)
            logger.info(f"runtime_overrides applied: {list(self.runtime_overrides.keys())}")

        for kw in get_all_enzyme_keywords():
            config["keyword_weights"].setdefault(kw.lower(), 5.0)
        for sub in get_all_substrate_keywords():
            config["keyword_weights"].setdefault(sub.lower(), 5.0)

        self._compile_keyword_pattern(config)
        return config

    def _compile_keyword_pattern(self, config: Optional[Dict[str, Any]] = None):
        effective_config = config or self.config
        self.keyword_weights_lower = {
            k.lower(): v for k, v in effective_config["keyword_weights"].items()
        }
        simple_keywords = [
            k.lower() for k in effective_config["keyword_weights"].keys()
            if k not in ["numeric_with_unit", "range"]
        ]
        if simple_keywords:
            pattern = "|".join(re.escape(k) for k in simple_keywords)
            self._keyword_pattern = re.compile(pattern, re.IGNORECASE)
        else:
            self._keyword_pattern = None

    # ---------- 文本提取与清洗 ----------
    def _is_noise(self, text: str) -> bool:
        if not text or len(text.strip()) < 3:
            return True
        text_lower = text.lower()
        compiled_remove = getattr(self, '_compiled_remove_patterns', None)
        if compiled_remove is None:
            compiled_remove = [re.compile(p) for p in self.config.get("remove_patterns", [])]
            self._compiled_remove_patterns = compiled_remove
        for compiled_pat in compiled_remove:
            if compiled_pat.search(text_lower):
                return True
        if self._looks_like_reference_tail(text):
            return True
        if self._looks_like_author_info(text):
            return True
        if re.match(r'^\s*[\d\W]+\s*$', text):
            return True
        return False

    def _looks_like_reference_tail(self, text: str) -> bool:
        """识别参考文献尾部行：年份/卷期/页码/期刊名+数字组合"""
        t = text.strip()
        if re.match(r'^\d+\.\s+\[', t):
            return True
        if re.match(r'^\d+\s+\d+[-,]\s*\d+\s*[.,]\s*\d{4}', t):
            return True
        if re.match(r'^[A-Z][a-z]+\s+\d+,\s+\d{4}', t):
            return True
        vol_page_year = r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\s+\d+\s*\(\d+\)\s*,\s*\d+[-,]\d+'
        if re.match(vol_page_year, t):
            return True
        journal_abbrev = r'^[A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+){0,3}\s+\d+\s*\(\d+\)\s*,?\s*\d+[-,]\d+\s+\d{4}$'
        if re.match(journal_abbrev, t):
            return True
        if re.match(r'^\d+\s+\(\d+\)\s+\d+-\d+\s+\d{4}', t):
            return True
        if re.match(r"^\d+\s+[A-Z][A-Za-z'’\-]+,\s+[A-Z]\.", t):
            return True
        if re.match(r"^\d+\s+[A-Z][A-Za-z'’\-]+.*\bet al\.", t):
            return True
        author_title_journal = r"^[A-Z][A-Za-z'’\-]+,\s+.+,\s+(?:[A-Z][A-Za-z.&\-]+(?:\s+[A-Z][A-Za-z.&\-]+){0,5})(?:\s+\d+|\.)"
        if re.match(author_title_journal, t):
            return True
        return False

    def _looks_like_author_info(self, text: str) -> bool:
        """识别作者/单位/ORCID/grant等噪声行"""
        t = text.strip()
        if re.search(r'orcid\.org/\d{4}', t, re.IGNORECASE):
            return True
        if re.search(r'\d{4}-\d{4}-\d{4}-\d{3}[\dX]', t):
            return True
        if re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', t):
            return True
        if re.search(r'grant\s+number', t, re.IGNORECASE):
            return True
        if re.search(r'funding\s+from', t, re.IGNORECASE):
            return True
        if re.search(r'national\s+natural\s+science\s+fou', t, re.IGNORECASE):
            return True
        if re.match(r'^\d+国自然|^\d+NSFC', t):
            return True
        if re.match(r'^[A-Z][a-z]+,\s*[A-Z]\.', t) and len(t) < 80:
            return True
        author_marker_count = len(re.findall(r'[§†‡]\s*\[[a-z](?:,\s*[a-z])*\]', t))
        if author_marker_count >= 2:
            return True
        name_comma_pattern = len(re.findall(r'[A-Z][a-z]+\s+[A-Z][a-z]+', t))
        if name_comma_pattern >= 3 and re.search(r'[§†‡*]', t):
            return True
        return False

    def _normalize_text(self, text: str) -> str:
        """基础文本清洗（内部通用版，不改词序）"""
        if not isinstance(text, str):
            return ""
        text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    # ============================================================
    # 三层文本处理：raw / normalized / search
    # ============================================================

    # 元素符号完整表（用于化学式识别，不枚举材料名）
    _ELEMENT_SYMBOLS = frozenset([
        'H','He','Li','Be','B','C','N','O','F','Ne',
        'Na','Mg','Al','Si','P','S','Cl','Ar','K','Ca',
        'Sc','Ti','V','Cr','Mn','Fe','Co','Ni','Cu','Zn',
        'Ga','Ge','As','Se','Br','Kr','Rb','Sr','Y','Zr',
        'Nb','Mo','Tc','Ru','Rh','Pd','Ag','Cd','In','Sn',
        'Sb','Te','I','Xe','Cs','Ba','La','Ce','Pr','Nd',
        'Pm','Sm','Eu','Gd','Tb','Dy','Ho','Er','Tm','Yb',
        'Lu','Hf','Ta','W','Re','Os','Ir','Pt','Au','Hg',
        'Tl','Pb','Bi','Po','At','Rn','Fr','Ra','Ac','Th',
        'Pa','U','Np','Pu','Am','Cm','Bk','Cf','Es','Fm',
        'Md','No','Lr','Rf','Db','Sg','Bh','Hs','Mt','Ds',
        'Rg','Cn','Nh','Fl','Mc','Lv','Ts','Og',
    ])

    # 单位指数模式：mL − 1 / mg mL − 1 / M − 1 s − 1 / cm − 1
    # 注意：这里的 −（U+2212）和普通 - 都要处理
    _UNIT_EXPONENT_PATTERN = re.compile(
        r'(?P<unit>[a-zA-Zμ]+)'          # 单位符号
        r'\s*[−\-]\s*'                    # 负号（Unicode minus 或 ASCII -）
        r'(?P<exp>\d+)'                   # 指数数字
        r'(?=\s|$|[,;.)\]])'             # 后跟空白/标点/结尾
    )

    @classmethod
    def _normalize_text_basic(cls, text: str) -> str:
        """
        第 1 层：raw_text → 仅做 unicode 标准化、换行合并、软断词修复、连续空白合并。
        不删除英文词间空格，不压缩化学式。
        """
        if not isinstance(text, str):
            return ""
        import unicodedata
        # NFC 归一化
        text = unicodedata.normalize('NFC', text)
        # 软连字符（U+00AD）
        text = text.replace('\u00ad', '')
        # 行末断词（如 "nano-\nparticle" → "nanoparticle"）
        text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)
        # 换行变空格
        text = text.replace('\n', ' ').replace('\r', ' ')
        # 连续空白合并
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @classmethod
    def _fix_split_words(cls, text: str) -> str:
        """
        第 2 层（字符级修复）：只修复明确的 ligature OCR 拆词和逐字拆词伪影。
        不删除普通英文词间空格。
        包含的修复：
        - fi gure → figure
        - effi ciency → efficiency
        - co effi cient → coefficient
        - 软连字符残留
        """
        if not text:
            return text
        # 常见 ligature 拆词（只修复有把握的）
        LIGATURE_FIXES = [
            (re.compile(r'\bfi\s+gure\b', re.IGNORECASE), 'figure'),
            (re.compile(r'\be\s+ffi\s+ciency\b', re.IGNORECASE), 'efficiency'),
            (re.compile(r'\bco\s+effi\s*cient\b', re.IGNORECASE), 'coefficient'),
            (re.compile(r'\bco\s+nfi\s*dence\b', re.IGNORECASE), 'confidence'),
            (re.compile(r'\bde\s+fi\s*ned\b', re.IGNORECASE), 'defined'),
            (re.compile(r'\bspeci\s+fi\s*c\b', re.IGNORECASE), 'specific'),
            (re.compile(r'\bidentifi\s*ed\b', re.IGNORECASE), 'identified'),
            (re.compile(r'\bclassi\s+fi\s*ed\b', re.IGNORECASE), 'classified'),
            # Unicode 替换符号
            (re.compile(r'(?<=[A-Za-z])￾(?=[A-Za-z])'), '-'),
            (re.compile(r'\xad'), ''),  # 软连字符
        ]
        for pat, repl in LIGATURE_FIXES:
            text = pat.sub(repl, text)
        return text

    @classmethod
    def _fix_chemical_formula_spacing(cls, text: str) -> str:
        """
        第 3 层（化学式专用）：合并被空格拆开的化学式 token。
        只在"疑似化学式片段"内执行，不影响普通英文句子。
        
        覆盖：
        Fe 3 O 4 → Fe3O4
        H 2 O 2 → H2O2
        MnCo 2 O 4 → MnCo2O4
        La 0.5 Sr 0.5 MnO 3-δ → La0.5Sr0.5MnO3-δ
        Fe 3+ / Fe 2+ / Ni 2+ → Fe3+ / Fe2+ / Ni2+
        mL − 1 → mL^-1
        mg mL − 1 → mg mL^-1
        M − 1 s − 1 → M^-1 s^-1
        """
        if not text:
            return text

        # --- 步骤 A：化学式 token 合并（基于 token 扫描） ---
        # 策略：按空格拆分 token，识别"化学 token 序列"并压缩中间空格。
        # 化学 token：以元素符号开头（含 2 字母元素如 Fe/Mn/Co），
        #             后可跟数字/小数/δ/价态。
        # 仅当连续序列 >= 2 个化学相关 token 时才合并。
        # 普通英文单词（全小写/大写首字母+多字母）不受影响。

        DIGIT_OR_CHARGE = re.compile(r'^\d+(?:\.\d+)?[+\-]?$')
        GREEK_VAR = re.compile(r'^[δxyzαβγ]$')

        def _is_element_token(tok: str) -> bool:
            if not tok or not tok[0].isupper():
                return False
            # 2字母元素（Fe, Mn, Co, Ni, Cu...）
            if len(tok) >= 2 and tok[1].islower():
                candidate2 = tok[:2]
                if candidate2 in cls._ELEMENT_SYMBOLS:
                    rest = tok[2:]
                    if not rest or re.match(r'^[\d.δxyzαβγ+\-]*$', rest) or (rest and rest[0].isupper()):
                        return True
            # 1字母元素（H, C, N, O, S, K, B, P, I, W...）
            candidate1 = tok[:1]
            if candidate1 in cls._ELEMENT_SYMBOLS:
                rest = tok[1:]
                if not rest or re.match(r'^[\d.δxyzαβγ+\-]*$', rest) or (rest and rest[0].isupper()):
                    return True
            return False

        def _can_follow_element(tok: str) -> bool:
            if DIGIT_OR_CHARGE.match(tok):
                return True
            if GREEK_VAR.match(tok):
                return True
            if _is_element_token(tok):
                return True
            return False

        parts = text.split(' ')
        if len(parts) > 1:
            remove_space_at = [False] * len(parts)
            i = 0
            while i < len(parts):
                tok = parts[i]
                if _is_element_token(tok):
                    j = i
                    seq_len = 1
                    while j < len(parts) - 1:
                        next_tok = parts[j + 1]
                        if _can_follow_element(next_tok):
                            remove_space_at[j] = True
                            j += 1
                            seq_len += 1
                        else:
                            break
                    if seq_len < 2:
                        for k in range(i, j + 1):
                            remove_space_at[k] = False
                    i = j + 1
                else:
                    i += 1
            result_parts = []
            for idx, part in enumerate(parts):
                result_parts.append(part)
                if idx < len(parts) - 1:
                    if not remove_space_at[idx]:
                        result_parts.append(' ')
            text = ''.join(result_parts)

        # --- 步骤 B：单位指数修复 unit − n → unit^-n ---
        MINUS_CHAR = r'[−\-]'

        unit_patterns = [
            # μg mL − 1 / mg mL − 1 / ng mL − 1
            (re.compile(
                r'(?<![A-Za-z])([μmMunpfk]?[gL])\s+([mMμ]?[LG])\s*' + MINUS_CHAR + r'\s*(\d+)(?=\s|$|[,;.)\]])',
            ), lambda m: f'{m.group(1)} {m.group(2)}^-{m.group(3)}'),
            # M − 1 s − 1
            (re.compile(
                r'(?<![A-Za-z])(M)\s*' + MINUS_CHAR + r'\s*1\s+(s)\s*' + MINUS_CHAR + r'\s*1(?=\s|$|[,;.)\]])',
            ), r'M^-1 s^-1'),
            # s − 1 / h − 1 / min − 1
            (re.compile(
                r'(?<![A-Za-z])(s|h|min)\s*' + MINUS_CHAR + r'\s*(\d+)(?=\s|$|[,;.)\]])',
            ), r'\1^-\2'),
            # cm − 1 / nm − 1 / mm − 1 / m − 1
            (re.compile(
                r'(?<![A-Za-z])(cm|nm|mm|m)\s*' + MINUS_CHAR + r'\s*(\d+)(?=\s|$|[,;.)\]])',
            ), r'\1^-\2'),
            # U mg − 1 / U g − 1
            (re.compile(
                r'(?<![A-Za-z])(U)\s+(m?g)\s*' + MINUS_CHAR + r'\s*(\d+)(?=\s|$|[,;.)\]])',
            ), lambda m: f'{m.group(1)} {m.group(2)}^-{m.group(3)}'),
            # mL − 1 / L − 1
            (re.compile(
                r'(?<![A-Za-z])([μmMunpfk]?[lL])\s*' + MINUS_CHAR + r'\s*(\d+)(?=\s|$|[,;.)\]])',
            ), r'\1^-\2'),
            # M − 1
            (re.compile(
                r'(?<![A-Za-z])(M)\s*' + MINUS_CHAR + r'\s*(\d+)(?=\s|$|[,;.)\]])',
            ), r'\1^-\2'),
            # 通用兜底（仅限明确的物理单位符号，防止 MOF-818 等被错误转换）
            # 覆盖常见的残留指数形式（已在具体规则中列出的不重复）
            (re.compile(
                r'(?<![A-Za-z])(min|hrs?|days?|weeks?)\s*' + MINUS_CHAR + r'\s*(\d+)(?=\s|$|[,;.)\]])',
            ), r'\1^-\2'),
        ]
        for pat, repl in unit_patterns:
            text = pat.sub(repl, text)

        return text

    @classmethod
    def _normalize_scientific_text_v2(cls, text: str) -> str:
        """
        给 LLM 的 normalized_text：三层处理流水线。
        保守、安全，不删英文词间空格。
        """
        if not isinstance(text, str):
            return ""
        s = cls._normalize_text_basic(text)
        s = cls._fix_split_words(s)
        s = cls._fix_chemical_formula_spacing(s)
        return s.strip()

    @classmethod
    def _normalize_for_search(cls, text: str) -> str:
        """
        生成 search_text：供关键词匹配和评分，可以更激进。
        先做 normalized，再转小写、去除标点、折叠空白。
        不得替代 normalized_text 用于 LLM 输入。
        """
        if not isinstance(text, str):
            return ""
        s = cls._normalize_scientific_text_v2(text)
        # 转小写
        s = s.lower()
        # 去除非字母数字（保留空格）
        s = re.sub(r'[^a-z0-9\s\-+^α-ω]', ' ', s)
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    # ============================================================
    # 内置回归测试（可独立运行）
    # ============================================================

    @staticmethod
    def _run_normalization_tests() -> bool:
        """运行文本归一化和化学式修复回归测试，返回 True 表示全部通过。"""
        import traceback
        p = NanozymePreprocessor

        cases_normalized = [
            # (输入, 期望不应出现的粘连, 说明)
            (
                "Source data are provided as a Source Data file.",
                ["Sourcedataareprovided", "sourcedataareprovided"],
                "普通英文句子不应粘连"
            ),
            (
                "Kinetic curves of A652 for monitoring the catalytic oxidation reaction.",
                ["Kineticcurvesof", "kineticcurvesof"],
                "普通英文句子不应粘连"
            ),
            (
                "shown in Figure 3a",
                ["shownin"],
                "普通英文句子不应粘连"
            ),
        ]
        cases_formula = [
            # (输入, 期望输出子串, 说明)
            ("Fe 3 O 4 nanozymes", "Fe3O4", "铁氧化物"),
            ("H 2 O 2 and O 2", "H2O2", "过氧化氢"),
            ("H 2 O 2 and O 2", "O2", "氧气"),
            ("MnCo 2 O 4 nanotubes", "MnCo2O4", "复合氧化物"),
            ("La 0.5 Sr 0.5 MnO 3 nanozymes", "La0.5Sr0.5MnO3", "钙钛矿化学式"),
            ("Fe 3+", "Fe3+", "铁离子价态"),
            ("Ni 2+", "Ni2+", "镍离子价态"),
        ]
        cases_unit = [
            ("10 μg mL − 1 concentration", "mL^-1", "浓度单位指数"),
            ("M − 1 s − 1 reaction rate", "M^-1 s^-1", "动力学速率常数单位"),
            ("cm − 1 absorbance", "cm^-1", "吸光度单位"),
        ]

        passed = 0
        failed = 0

        print("=== 文本归一化回归测试 ===")
        for inp, bad_substrs, desc in cases_normalized:
            result = p._normalize_scientific_text_v2(inp)
            ok = True
            for bad in bad_substrs:
                if bad in result:
                    print(f"  FAIL [{desc}]: 输入='{inp}', 结果='{result}', 不应含='{bad}'")
                    ok = False
                    failed += 1
                    break
            if ok:
                print(f"  PASS [{desc}]: '{inp}' → '{result}'")
                passed += 1

        print("\n=== 化学式修复回归测试 ===")
        for inp, expected_sub, desc in cases_formula:
            result = p._fix_chemical_formula_spacing(p._normalize_text_basic(inp))
            if expected_sub in result:
                print(f"  PASS [{desc}]: '{inp}' → '{result}'")
                passed += 1
            else:
                print(f"  FAIL [{desc}]: 输入='{inp}', 结果='{result}', 期望含='{expected_sub}'")
                failed += 1

        print("\n=== 单位指数修复回归测试 ===")
        for inp, expected_sub, desc in cases_unit:
            result = p._fix_chemical_formula_spacing(inp)
            if expected_sub in result:
                print(f"  PASS [{desc}]: '{inp}' → '{result}'")
                passed += 1
            else:
                print(f"  FAIL [{desc}]: 输入='{inp}', 结果='{result}', 期望含='{expected_sub}'")
                failed += 1

        print(f"\n总计: {passed} 通过, {failed} 失败")
        return failed == 0

    _HARD_RECALL_PATTERNS = [
        (r'(?i)\bK[_ ]?m\b|Kₘ', 'Km'),
        (r'(?i)\bV[_ ]?max\b|V[_ ]?m\b', 'Vmax'),
        (r'(?i)\bkcat(?:\s*/\s*Km)?\b', 'kcat'),
        (r'(?i)\bMichaelis(?:[- ]Menten)?\b', 'Michaelis-Menten'),
        (r'(?i)\bLineweaver(?:[- ]Burk)?\b', 'Lineweaver-Burk'),
        (r'(?i)\bkinetic\s+parameters?\b', 'kinetic_parameters'),
        (r'(?i)\b(?:mM|μM|uM|nM|pM)\b', 'concentration_unit'),
        (r'(?i)\bM\s*s[_\s^-]*1\b|M\s*/\s*s\b|μM\s*min[_\s^-]*1\b', 'rate_unit'),
        (r'[×x*]\s*10[_\s^-]*\d+|\b\d+e[+-]?\d+\b', 'scientific_notation'),
    ]

    _HARD_RECALL_TABLE_FIGURE_PATTERN = (
        r'(?i)\bTable\s+S?\d+\b|Fig\.?\s+\d+|Figure\s+\d+'
    )
    _HARD_RECALL_CONTEXT_WORDS = (
        r'(?i)\bkinetics?|activity|assay|parameter|Km|Vmax|kcat|Michaelis\b'
    )

    def _normalize_scientific_text(self, text: str) -> str:
        """
        给 LLM 的 normalized_text（向后兼容入口）。
        调用三层处理流水线：basic → split_words → formula_spacing。
        """
        return self._normalize_scientific_text_v2(text)

    def _hard_recall_guardrail(self, sentence: SentenceInfo) -> bool:
        text = sentence.normalized_text or sentence.text
        if not text:
            return False
        self._ensure_compiled_patterns()
        hit_patterns = []
        for compiled_pat, label in self._COMPILED_HARD_RECALL_PATTERNS:
            if compiled_pat.search(text):
                hit_patterns.append(label)
        if not hit_patterns:
            table_fig_match = self._COMPILED_HARD_RECALL_TABLE_FIGURE_PATTERN.search(text)
            if table_fig_match and self._COMPILED_HARD_RECALL_CONTEXT_WORDS.search(text):
                hit_patterns.append('table_figure_with_kinetics_context')
        if hit_patterns:
            sentence.hard_recall = True
            sentence.hard_recall_patterns = hit_patterns
            return True
        return False

    _KINETICS_SIGNAL_PATTERNS = [
        (r'(?i)\bK[_ ]?m\b|Kₘ', 'Km'),
        (r'(?i)\bV[_ ]?max\b|V[_ ]?m\b', 'Vmax'),
        (r'(?i)\bkcat(?:\s*/\s*Km)?\b', 'kcat'),
        (r'(?i)\bMichaelis(?:[- ]Menten)?\b', 'Michaelis-Menten'),
        (r'(?i)\bLineweaver(?:[- ]Burk)?\b', 'Lineweaver-Burk'),
        (r'(?i)\bkinetic\s+parameters?\b', 'kinetic_parameters'),
        (r'(?i)\bcatalytic\s+efficiency\b', 'catalytic_efficiency'),
        (r'(?i)\bturnover\s+(?:number|frequency)\b', 'turnover'),
        (r'(?i)\baffinity\b', 'affinity'),
        (r'(?i)\bsteady[- ]state\b', 'steady_state'),
    ]

    _KINETICS_NUMERIC_PATTERN = re.compile(
        r'(?i)(?:mM|μM|uM|nM|pM)\s*(?:s[_\s^-]*1|min[_\s^-]*1|M[_\s^-]*1\s*s[_\s^-]*1|U\s*/\s*mg)'
        r'|[×x*]\s*10[_\s^-]*\d+'
        r'|\b\d+\.?\d*\s*(?:mM|μM|uM|nM|pM|s[_\s^-]*1|min[_\s^-]*1)\b'
    )

    _KINETICS_PROXIMITY_PATTERN = re.compile(
        r'(?:Km|Vmax|kcat|kinetic|Michaelis|affinity|catalytic\s+efficiency)'
        r'.{0,60}'
        r'(?:\d+\.?\d*\s*(?:mM|μM|uM|nM|pM|s[_\s^-]*1|min[_\s^-]*1|M[_\s^-]*1))'
        r'|'
        r'(?:\d+\.?\d*\s*(?:mM|μM|uM|nM|pM|s[_\s^-]*1|min[_\s^-]*1|M[_\s^-]*1))'
        r'.{0,60}'
        r'(?:Km|Vmax|kcat|kinetic|Michaelis|affinity|catalytic\s+efficiency)',
        re.IGNORECASE,
    )

    _APPLICATION_SIGNAL_PATTERNS = [
        r'(?i)\bdetection\b', r'(?i)\bsensing\b', r'(?i)\bbiosensing\b',
        r'(?i)\bLOD\b', r'(?i)\bdetection\s+limit\b', r'(?i)\blinear\s+range\b',
        r'(?i)\bsample\b', r'(?i)\banalyte\b', r'(?i)\btarget\s+(?:analyte|ion|molecule)\b',
        r'(?i)\bselectivity\b', r'(?i)\banti[- ]interference\b',
        r'(?i)\btumou?r\s+therapy\b', r'(?i)\bphotodynamic\b',
        r'(?i)\bantibacterial\b', r'(?i)\bwound\s+heal\b',
        r'(?i)\bwater\s+treatment\b', r'(?i)\bfood\s+safety\b',
        r'(?i)\bdegradation\b', r'(?i)\bpollutant\b',
        r'(?i)\bROS\s+scavenging\b', r'(?i)\bantioxidant\b',
        r'(?i)\bbioimaging\b', r'(?i)\banti[- ]inflammatory\b',
        r'(?i)\bchemodynamic\b', r'(?i)\bphotothermal\b',
        r'(?i)\bdrug\s+resistance\b', r'(?i)\bcytoprotection\b',
        r'(?i)\bsteriliz\b', r'(?i)\bantibiofilm\b',
        r'(?i)\breal[- ]time\b', r'(?i)\bpoint[- ]of[- ]care\b',
        r'(?i)\bclinical\b', r'(?i)\bin\s+vivo\b',
    ]

    _ACTIVITY_SIGNAL_PATTERNS = [
        r'(?i)\bperoxidase[- ]like\b', r'(?i)\boxidase[- ]like\b',
        r'(?i)\bcatalase[- ]like\b', r'(?i)\bcatechol\s+oxidase[- ]like\b',
        r'(?i)\bsuperoxide\s+dismutase[- ]like\b', r'(?i)\bglutathione\s+peroxidase[- ]like\b',
        r'(?i)\bphosphatase[- ]like\b', r'(?i)\bnuclease[- ]like\b',
        r'(?i)\bglucose\s+oxidase[- ]like\b', r'(?i)\besterase[- ]like\b',
        r'(?i)\benzyme[- ]like\s+activity\b', r'(?i)\bnanozyme\s+activity\b',
        r'(?i)\bsubstrate\s+oxidation\b', r'(?i)\bcatalytic\s+activity\b',
        r'(?i)\bmimic(?:s|king|ed)?\b.{0,30}\bactivity\b',
    ]

    _SUBSTRATE_KEYWORDS_EXTRA = [
        'DAB', 'DAF-FM', 'DHE', 'L-tyrosine',
    ]

    _CAPTION_TYPE_PATTERNS = {
        "kinetics_caption": [
            r'(?i)\bkinetic', r'(?i)\bMichaelis[- ]Menten', r'(?i)\bLineweaver',
            r'(?i)\bKm\b', r'(?i)\bVmax\b', r'(?i)\bkcat\b',
            r'(?i)\bcatalytic\s+efficiency', r'(?i)\bdouble[- ]reciprocal',
        ],
        "mechanism_caption": [
            r'(?i)\bmechanism\b', r'(?i)\bpathway\b', r'(?i)\bintermediate\b',
            r'(?i)\bROS\b', r'(?i)\bradical\b', r'(?i)\belectron\s+transfer\b',
            r'(?i)\bcharge\s+transfer\b', r'(?i)\bFenton\b',
            r'(?i)\boxygen\s+vacancy\b', r'(?i)\bactive\s+site\b',
            r'(?i)\bDFT\b', r'(?i)\badsorption\s+energy\b',
        ],
        "application_caption": [
            r'(?i)\bdetection\b', r'(?i)\bsensing\b', r'(?i)\bLOD\b',
            r'(?i)\bdetection\s+limit\b', r'(?i)\blinear\s+range\b',
            r'(?i)\bselectivity\b', r'(?i)\banti[- ]interference\b',
            r'(?i)\btherapy\b', r'(?i)\bantibacterial\b',
            r'(?i)\bwound\b', r'(?i)\bdegradation\b',
        ],
        "comparison_caption": [
            r'(?i)\bcomparison\b', r'(?i)\bcompared\b', r'(?i)\bversus\b',
            r'(?i)\bsuperior\b', r'(?i)\boutperform\b', r'(?i)\bbenchmark\b',
            r'(?i)\bliterature\b', r'(?i)\brepresentative\s+nanozyme\b',
        ],
        "morphology_caption": [
            r'(?i)\bSEM\b', r'(?i)\bTEM\b', r'(?i)\bHAADF\b',
            r'(?i)\bAFM\b', r'(?i)\bmorphology\b', r'(?i)\brepresentative\b',
            r'(?i)\bfresh\b', r'(?i)\bas[- ]prepared\b',
        ],
    }

    _MATERIAL_MORPHOLOGY_PATTERNS = [
        r'(?i)\bnanotubes?\b', r'(?i)\bnanoparticles?\b', r'(?i)\bnanosheets?\b',
        r'(?i)\bnanorods?\b', r'(?i)\bnanowires?\b', r'(?i)\bnanozymes?\b',
        r'(?i)\bcomposites?\b', r'(?i)\bframeworks?\b', r'(?i)\bMOF\b',
        r'(?i)\bsingle[- ]atom\b', r'(?i)\bdual[- ]atom\b',
        r'(?i)\bcarbon\s+dots?\b', r'(?i)\bCDs\b',
        r'(?i)\bdoped\b', r'(?i)\boxygen\s+vacancy\b',
        r'(?i)\bdefects?\b', r'(?i)\bactive\s+sites?\b',
    ]

    _APPLICATION_TYPE_PATTERNS = {
        "biosensing": [r'(?i)\bbiosensing\b', r'(?i)\bsensing\b', r'(?i)\bdetection\b'],
        "therapeutic": [r'(?i)\btherapy\b', r'(?i)\btherapeutic\b', r'(?i)\btumou?r\b'],
        "environmental": [r'(?i)\bdegradation\b', r'(?i)\bpollutant\b', r'(?i)\bwater\s+treatment\b'],
        "diagnostic": [r'(?i)\bdiagnos\b', r'(?i)\bclinical\b'],
        "antioxidant": [r'(?i)\bantioxidant\b', r'(?i)\bROS\s+scavenging\b', r'(?i)\bcytoprotection\b'],
        "food_safety": [r'(?i)\bfood\s+safety\b', r'(?i)\bfood\s+detection\b'],
    }

    _COMPILED_KINETICS_SIGNAL_PATTERNS = None
    _COMPILED_APPLICATION_SIGNAL_PATTERNS = None
    _COMPILED_ACTIVITY_SIGNAL_PATTERNS = None
    _COMPILED_CAPTION_TYPE_PATTERNS = None
    _COMPILED_MATERIAL_MORPHOLOGY_PATTERNS = None
    _COMPILED_APPLICATION_TYPE_PATTERNS = None
    _COMPILED_ENZYME_MENTION_PATTERN = None
    _CACHED_ALL_SUBSTRATE_KEYWORDS = None
    _COMPILED_SPECIFICITY_PATTERN = None
    _COMPILED_HARD_RECALL_PATTERNS = None
    _COMPILED_HARD_RECALL_TABLE_FIGURE_PATTERN = None
    _COMPILED_HARD_RECALL_CONTEXT_WORDS = None
    _COMPILED_NORMALIZE_SCIENTIFIC_PATTERNS = None
    _COMPILED_NUMERIC_UNIT_PATTERN = None
    _COMPILED_RANGE_PATTERN = None
    _COMPILED_TAG_PATTERNS = None

    @classmethod
    def _ensure_compiled_patterns(cls):
        if cls._COMPILED_KINETICS_SIGNAL_PATTERNS is None:
            cls._COMPILED_KINETICS_SIGNAL_PATTERNS = [
                (re.compile(p), label) for p, label in cls._KINETICS_SIGNAL_PATTERNS
            ]
        if cls._COMPILED_APPLICATION_SIGNAL_PATTERNS is None:
            cls._COMPILED_APPLICATION_SIGNAL_PATTERNS = [
                re.compile(p) for p in cls._APPLICATION_SIGNAL_PATTERNS
            ]
        if cls._COMPILED_ACTIVITY_SIGNAL_PATTERNS is None:
            cls._COMPILED_ACTIVITY_SIGNAL_PATTERNS = [
                re.compile(p) for p in cls._ACTIVITY_SIGNAL_PATTERNS
            ]
        if cls._COMPILED_CAPTION_TYPE_PATTERNS is None:
            cls._COMPILED_CAPTION_TYPE_PATTERNS = {
                ctype: [re.compile(p) for p in pats]
                for ctype, pats in cls._CAPTION_TYPE_PATTERNS.items()
            }
        if cls._COMPILED_MATERIAL_MORPHOLOGY_PATTERNS is None:
            cls._COMPILED_MATERIAL_MORPHOLOGY_PATTERNS = [
                re.compile(p) for p in cls._MATERIAL_MORPHOLOGY_PATTERNS
            ]
        if cls._COMPILED_APPLICATION_TYPE_PATTERNS is None:
            cls._COMPILED_APPLICATION_TYPE_PATTERNS = {
                app_type: [re.compile(p) for p in pats]
                for app_type, pats in cls._APPLICATION_TYPE_PATTERNS.items()
            }
        if cls._COMPILED_ENZYME_MENTION_PATTERN is None:
            _enzyme_base_names = sorted(
                [meta["keywords"][0] for meta in ENZYME_REGISTRY.values()],
                key=len, reverse=True,
            )
            cls._COMPILED_ENZYME_MENTION_PATTERN = re.compile(
                r"(?i)\b(" + "|".join(re.escape(n) for n in _enzyme_base_names) + r")[- ]like\b"
            )
        if cls._COMPILED_SPECIFICITY_PATTERN is None:
            _spec_names = sorted(
                [meta["keywords"][0] for meta in ENZYME_REGISTRY.values()],
                key=len, reverse=True,
            )
            cls._COMPILED_SPECIFICITY_PATTERN = re.compile(
                r"(?i)\b(no|without|lacks?)\s+(?:obvious\s+)?(?:"
                + "|".join(re.escape(n) for n in _spec_names)
                + r")[- ]like activity\b"
            )
        if cls._COMPILED_HARD_RECALL_PATTERNS is None:
            cls._COMPILED_HARD_RECALL_PATTERNS = [
                (re.compile(p), label) for p, label in cls._HARD_RECALL_PATTERNS
            ]
            cls._COMPILED_HARD_RECALL_TABLE_FIGURE_PATTERN = re.compile(
                cls._HARD_RECALL_TABLE_FIGURE_PATTERN, re.IGNORECASE
            )
            cls._COMPILED_HARD_RECALL_CONTEXT_WORDS = re.compile(
                cls._HARD_RECALL_CONTEXT_WORDS, re.IGNORECASE
            )
        if cls._COMPILED_NORMALIZE_SCIENTIFIC_PATTERNS is None:
            # *** 关键：已删除 r'(?<=[a-z])\s+(?=[a-z]{2,})' -> '' 这条规则 ***
            # 该规则会把正常英文词粘连：shownin / kineticcurvesof / source dataareprovided
            # 现在只做保守的、明确有把握的修复
            cls._COMPILED_NORMALIZE_SCIENTIFIC_PATTERNS = [
                # ligature / OCR 字符修复（明确有把握的）
                (re.compile(r'\bfi\s+gure\b', re.IGNORECASE), 'figure'),
                (re.compile(r'\be\s+ffi\s+ciency\b', re.IGNORECASE), 'efficiency'),
                (re.compile(r'\bco\s+effi\s*cient\b', re.IGNORECASE), 'coefficient'),
                (re.compile(r'\bco\s+nfi\s*dence\b', re.IGNORECASE), 'confidence'),
                # 特殊 Unicode 替换符号
                (re.compile(r'(?<=[A-Za-z])￾(?=[A-Za-z])'), '-'),
                # 软连字符和行末连字符（单词内部跨行断词）
                (re.compile(r'(\w)\xad(\w)'), r'\1\2'),
                # 数字间范围连字符
                (re.compile(r'(\d)\s+-\s+(\d)'), r'\1-\2'),
                # 合并末尾多余空白
                (re.compile(r'\s+'), ' '),
            ]
        if cls._COMPILED_NUMERIC_UNIT_PATTERN is None:
            cls._COMPILED_NUMERIC_UNIT_PATTERN = re.compile(
                r'\d+\.?\d*\s*(mM|μM|uM|nM|pM|nm|°C|mg/mL|μg/mL|mg·L⁻¹|g/L|min|s|h⁻¹|s⁻¹|M⁻¹s⁻¹|U/mg|ppm|ppb|K|kPa)'
            )
            cls._COMPILED_RANGE_PATTERN = re.compile(
                r'\d+\s*-\s*\d+\s*(mM|μM|nM|pM)'
            )
        if cls._COMPILED_TAG_PATTERNS is None:
            cls._COMPILED_TAG_PATTERNS = {
                "paper": [re.compile(r"(?i)\b(herein|here we|we report|we demonstrate|we show|we reveal|we found|our findings|this work|this study|these results|this result)\b")],
                "system": [
                    re.compile(r"(?i)\b(single[- ]atom|single atom|dual[- ]atom|binuclear|trinuclear|atomically dispersed)\b"),
                    re.compile(r"(?i)\b(active sites?|active-site|coordination environment|metal centers?|oxygen vacancies?|defects?)\b"),
                    re.compile(r"(?i)\b(nanotubes?|nanoparticles?|nanosheets?|nanorods?|nanowires?|nanozymes?|composites?|frameworks?|carbon spheres?|carbon shells?|gels?)\b"),
                    re.compile(r"(?i)\b(loaded (?:on|in|inside|outside)|embedded|encapsulated|doped|undoped)\b"),
                ],
                "system_extra": re.compile(r"(?i)\b(catalyst|nanozyme|site|center|shell|sphere|tube|sheet|dot|framework|gel|carbon)\b"),
                "assay": [
                    re.compile(r"(?i)\b(tmb|abts|opd|o-?phenylenediamine|h2o2|hydrogen peroxide|substrate|assay|probe|chromogenic)\b"),
                    re.compile(r"(?i)\b(uv-?vis|absorbance|a\d{3}|raman|sers|fluorescence)\b"),
                ],
                "kinetics": [
                    re.compile(r"(?i)\b(km|vmax|kcat|michaelis(?:[- ]menten)?|lineweaver(?:[- ]burk)?|steady[- ]state kinetic|kinetic parameters?)\b"),
                    re.compile(r"(?i)\b(catalytic efficiency|turnover|reaction rate|affinity)\b"),
                ],
                "structure": [
                    re.compile(r"(?i)\b(tem|hrtem|haadf-stem|eels|eds mapping|edx|stem|saed|xrd|xps|xafs|xanes|exafs|icp-aes|bet|ft-?ir|uv-?vis|raman|sers)\b"),
                    re.compile(r"(?i)\b(active sites?|active-site|coordination environment|atomic dispersion)\b"),
                ],
                "mechanism": [
                    re.compile(r"(?i)\b(mechanism|intermediate|pathway|cause of activity|specificity)\b"),
                    re.compile(r"(?i)\b(reactive oxygen species|ros|hydroxyl radical|superoxide|singlet oxygen|fenton-like|electron transfer|charge transfer|o2 activation)\b"),
                    re.compile(r"(?i)\b(fe=o|o=fe=o|oxygen vacancies?)\b"),
                ],
                "comparison": [
                    re.compile(r"(?i)\b(compared with|compared to|compared against|versus|vs\.?|superior to|higher than|lower than|better than)\b"),
                    re.compile(r"(?i)\b(outperform(?:s|ed)?|enhanced|improved|weaker than|stronger than|fold|times? higher)\b"),
                    re.compile(r"(?i)\b(inside|outside|doped|undoped)\b"),
                ],
                "application": [
                    re.compile(r"(?i)\b(sensing|detection|biosensing|linear range|detection limit|selectivity|anti-interference)\b"),
                    re.compile(r"(?i)\b(tumou?r therapy|photodynamic|catalytic therapy|drug resistance|antitumou?r|cisplatin)\b"),
                    re.compile(r"(?i)\b(degradation|pollutant removal|wastewater treatment)\b"),
                    re.compile(r"(?i)\b(antibacterial|antibiofilm|bacteriostatic|bactericidal|steriliz)\b"),
                    re.compile(r"(?i)\b(wound heal|tissue repair|regenerat)\b"),
                    re.compile(r"(?i)\b(cytoprotection|cytoprotective|cell protect)\b"),
                    re.compile(r"(?i)\b(ros scavenging|radical scavenging|antioxidant|free radical|oxidative stress)\b"),
                    re.compile(r"(?i)\b(bioimaging|fluorescence imaging|cell imaging|in vivo imaging)\b"),
                    re.compile(r"(?i)\b(anti-inflammatory|inflammation|antiinflammatory)\b"),
                    re.compile(r"(?i)\b(food safety|food detection|food analysis|foodborne)\b"),
                    re.compile(r"(?i)\b(water treatment|heavy metal removal|environmental remediation)\b"),
                    re.compile(r"(?i)\b(chemodynamic|sonodynamic|photothermal)\b"),
                ],
                "background": [
                    re.compile(r"(?i)^in recent years\b"),
                    re.compile(r"(?i)^for example\b"),
                    re.compile(r"(?i)^however\b"),
                    re.compile(r"(?i)^various\b"),
                    re.compile(r"(?i)^many\b"),
                ],
                "activity_extra": [
                    re.compile(r"(?i)\bmulti(?:ple)? enzyme[- ]like activit(?:y|ies)\b"),
                    re.compile(r"(?i)\bmimic(?:s|king|ed)?\b.{0,40}\b(enzyme|activity|activities)\b"),
                ],
            }

    def _detect_kinetics_signal(self, text: str) -> bool:
        if not text:
            return False
        self._ensure_compiled_patterns()
        for compiled_pat, _ in self._COMPILED_KINETICS_SIGNAL_PATTERNS:
            if compiled_pat.search(text):
                return True
        if self._KINETICS_NUMERIC_PATTERN.search(text):
            return True
        if self._KINETICS_PROXIMITY_PATTERN.search(text):
            return True
        return False

    def _detect_application_signal(self, text: str) -> bool:
        if not text:
            return False
        self._ensure_compiled_patterns()
        return any(pat.search(text) for pat in self._COMPILED_APPLICATION_SIGNAL_PATTERNS)

    def _detect_activity_signal(self, text: str) -> bool:
        if not text:
            return False
        self._ensure_compiled_patterns()
        return any(pat.search(text) for pat in self._COMPILED_ACTIVITY_SIGNAL_PATTERNS)

    def _detect_material_signal(self, text: str) -> bool:
        if not text:
            return False
        if self._contains_formula_like_material_token(text):
            return True
        self._ensure_compiled_patterns()
        return any(pat.search(text) for pat in self._COMPILED_MATERIAL_MORPHOLOGY_PATTERNS)

    def _extract_candidate_enzyme_mentions(self, text: str) -> List[str]:
        if not text:
            return []
        self._ensure_compiled_patterns()
        mentions: List[str] = []
        seen_etypes: set = set()
        for match in self._COMPILED_ENZYME_MENTION_PATTERN.finditer(text):
            matched_kw = match.group(1).lower()
            for _etype, _meta in ENZYME_REGISTRY.items():
                if _etype in seen_etypes:
                    continue
                if any(kw.lower() == matched_kw for kw in _meta["keywords"]):
                    canonical = EnzymeType.normalize_canonical(_etype.value)
                    if canonical not in mentions:
                        mentions.append(canonical)
                    seen_etypes.add(_etype)
                    break
        return mentions

    def _extract_candidate_substrate_mentions(self, text: str) -> List[str]:
        if not text:
            return []
        text_lower = text.lower()
        seen: set = set()
        mentions: List[str] = []
        if self._CACHED_ALL_SUBSTRATE_KEYWORDS is None:
            self._CACHED_ALL_SUBSTRATE_KEYWORDS = get_all_substrate_keywords()
        for kw in self._CACHED_ALL_SUBSTRATE_KEYWORDS:
            if kw.lower() in text_lower and kw not in seen:
                mentions.append(kw)
                seen.add(kw)
        for sub in self._SUBSTRATE_KEYWORDS_EXTRA:
            if sub.lower() in text_lower and sub not in seen:
                mentions.append(sub)
                seen.add(sub)
        return mentions[:8]

    def _extract_candidate_application_mentions(self, text: str) -> List[str]:
        if not text:
            return []
        self._ensure_compiled_patterns()
        mentions: List[str] = []
        for app_type, compiled_pats in self._COMPILED_APPLICATION_TYPE_PATTERNS.items():
            if any(pat.search(text) for pat in compiled_pats):
                if app_type not in mentions:
                    mentions.append(app_type)
        return mentions

    def _classify_signal_type(self, text: str, value_tags: List[str]) -> str:
        has_activity = self._detect_activity_signal(text) or 'activity' in value_tags
        has_application = self._detect_application_signal(text) or 'application' in value_tags
        has_kinetics = self._detect_kinetics_signal(text) or 'kinetics' in value_tags
        signals = []
        if has_kinetics:
            signals.append('kinetics')
        if has_activity:
            signals.append('activity')
        if has_application:
            signals.append('application')
        return '+'.join(signals) if signals else ''

    def _classify_caption_type(self, caption: str) -> str:
        if not caption:
            return "unknown"
        self._ensure_compiled_patterns()
        for ctype, compiled_pats in self._COMPILED_CAPTION_TYPE_PATTERNS.items():
            if any(pat.search(caption) for pat in compiled_pats):
                return ctype
        return "general"

    def _annotate_sentence_signals(self, sentence: SentenceInfo) -> None:
        text = sentence.normalized_text or sentence.text
        sentence.contains_kinetics_signal = self._detect_kinetics_signal(text)
        sentence.contains_material_signal = self._detect_material_signal(text)
        sentence.signal_type = self._classify_signal_type(text, sentence.value_tags)
        sentence.candidate_enzyme_mentions = self._extract_candidate_enzyme_mentions(text)
        sentence.candidate_substrate_mentions = self._extract_candidate_substrate_mentions(text)
        sentence.candidate_application_mentions = self._extract_candidate_application_mentions(text)
        if sentence.source_kind == "caption":
            parsed = self._parse_caption_label(text)
            if parsed:
                sentence.figure_label = f"{parsed[0]}_{parsed[1]:03d}"
            # Kinetics/mechanism captions are core evidence — guarantee survival in budget
            caption_type = self._classify_caption_type(text)
            if caption_type in ("kinetics_caption", "mechanism_caption"):
                if not sentence.hard_recall:
                    sentence.hard_recall = True
                    sentence.hard_recall_patterns = list(dict.fromkeys(
                        list(sentence.hard_recall_patterns or []) + [f"caption_type:{caption_type}"]
                    ))

    def _hard_recall_context_window(self, sentence: SentenceInfo) -> int:
        text = sentence.normalized_text or sentence.text or ""
        if re.search(r"(?i)\brespectively\b", text):
            return 1
        if self._is_incomplete_sentence(text):
            return 1
        if re.search(r"(?i)\b(?:K\s*m|V\s*m|Km|Vmax|Michaelis|Lineweaver|kinetic parameters?)\b", text):
            return 1
        if re.search(self._HARD_RECALL_TABLE_FIGURE_PATTERN, text) and re.search(self._HARD_RECALL_CONTEXT_WORDS, text):
            return 1
        return 0

    def _expand_hard_recall_context(
        self,
        sentences: List[SentenceInfo],
        kept: List[SentenceInfo],
    ) -> Tuple[List[SentenceInfo], int]:
        """Keep paragraph/neighbor context around hard-recalled kinetics evidence."""
        if not sentences or not kept:
            return kept, 0

        kept_ids = {id(sentence) for sentence in kept}
        expanded: List[SentenceInfo] = list(kept)
        ordered = list(sentences)
        index_by_id = {id(sentence): idx for idx, sentence in enumerate(ordered)}
        by_block: Dict[str, List[SentenceInfo]] = defaultdict(list)
        for sentence in ordered:
            if sentence.block_id:
                by_block[sentence.block_id].append(sentence)

        def allowed_context(sentence: SentenceInfo) -> bool:
            if sentence.source_kind == "figure_ocr":
                return False
            reason = self._drop_before_scoring(sentence)
            return reason not in {
                "boilerplate",
                "author_info",
                "reference_tail",
                "reference_entry",
                "figure_ocr_fragment",
                "supplementary_toc",
                "repeated_title",
            }

        def add_context(sentence: SentenceInfo) -> None:
            if id(sentence) in kept_ids:
                sentence.hard_recall = True
                sentence.hard_recall_patterns = list(dict.fromkeys(
                    list(sentence.hard_recall_patterns or []) + ["context_expansion"]
                ))
                return
            if not allowed_context(sentence):
                return
            sentence.hard_recall = True
            sentence.hard_recall_patterns = list(dict.fromkeys(
                list(sentence.hard_recall_patterns or []) + ["context_expansion"]
            ))
            expanded.append(sentence)
            kept_ids.add(id(sentence))

        for anchor in [sentence for sentence in ordered if sentence.hard_recall]:
            if anchor.block_id:
                block_sentences = by_block.get(anchor.block_id, [])
                if 1 < len(block_sentences) <= 8:
                    for peer in block_sentences:
                        add_context(peer)
            window = self._hard_recall_context_window(anchor)
            if window <= 0:
                continue
            anchor_idx = index_by_id.get(id(anchor))
            if anchor_idx is None:
                continue
            for neighbor in ordered[max(0, anchor_idx - window): min(len(ordered), anchor_idx + window + 1)]:
                add_context(neighbor)

        return expanded, max(0, len(expanded) - len(kept))

    def _normalize_heading_token_spaces(self, text: str) -> str:
        normalized = self._normalize_text(text)
        return re.sub(
            r"\b(?:[A-Z]\s+){2,}[A-Z]\b",
            lambda match: match.group(0).replace(" ", ""),
            normalized,
        )

    def _detect_section(self, text: str) -> str:
        """根据文本内容识别章节"""
        for section, pattern in self.config["section_patterns"].items():
            if re.match(pattern, text.strip()):
                return section
        return "unknown"

    def _detect_review(self, title: str) -> bool:
        review_patterns = [
            r"(?i)\breview\b",
            r"(?i)\bperspective\b",
            r"(?i)\brecent advances\b",
            r"(?i)\bprogress in\b",
            r"(?i)\badvances in\b",
            r"(?i)\bmini-?review\b",
        ]
        return any(re.search(p, title) for p in review_patterns)

    def _detect_communication(self, title: str) -> bool:
        comm_patterns = [
            r"(?i)\bcommunication\b",
            r"(?i)\bletter\b",
            r"(?i)\bcorrespondence\b",
        ]
        if any(re.search(p, title) for p in comm_patterns):
            return True
        page_count = self.data.get("number of pages")
        try:
            page_count = int(page_count) if page_count is not None else None
        except (TypeError, ValueError):
            page_count = None
        if page_count is not None and page_count <= 5:
            has_abstract = False
            for item in self._iter_layout_items():
                if item.get("page number", 1) > 2:
                    break
                content = self._normalize_text(item.get("content", ""))
                if content and re.match(r"(?i)^abstract\b", content):
                    has_abstract = True
                    break
            if not has_abstract:
                section_names = set()
                for block in self.blocks:
                    if block.get("section") and block["section"] not in ("unknown", "backmatter"):
                        section_names.add(block["section"].lower())
                research_indicators = {"introduction", "experimental", "results", "results_like", "methodology", "materials"}
                if section_names & research_indicators:
                    return False
                return True
        return False

    def _detect_document_kind(self, text: Optional[str] = None) -> str:
        supplementary_heading_patterns = [
            r"(?i)^(?:supporting|supplementary)\s+(?:information|material|data)$",
            r"(?i)^supporting info$",
            r"(?i)^si$",
        ]
        supplementary_global_patterns = [
            r"(?i)\bsupporting information\b",
            r"(?i)\bsupplementary information\b",
            r"(?i)\bsupplementary material\b",
            r"(?i)\bsupplementary data\b",
            r"(?i)\bsupporting info\b",
            r"(?i)\belectronic supplementary information\b",
            r"(?i)\belectronic supporting information\b",
            r"(?i)\besi\b",
            r"(?i)\bappendix\b",
            r"(?i)\bsupporting online material\b",
            r"(?i)\bsupplementary note\b",
            r"(?i)\bsupplementary method\b",
            r"(?:^|[\s_.-])SI(?:$|[\s_.-])",
        ]
        if text is not None:
            normalized = self._normalize_heading_token_spaces(text)
            normalized = re.sub(r"^[^\w]+|[^\w]+$", "", normalized).strip()
            return "supplementary" if any(re.fullmatch(pattern, normalized) for pattern in supplementary_heading_patterns) else "main"

        candidates = [
            getattr(getattr(self, "json_path", None), "stem", ""),
            getattr(self, "data", {}).get("title", ""),
            getattr(self, "data", {}).get("file name", ""),
        ]
        for candidate in candidates:
            normalized_candidate = self._normalize_heading_token_spaces(str(candidate))
            if candidate and any(re.search(pattern, normalized_candidate) for pattern in supplementary_global_patterns):
                if self._has_main_document_structure():
                    logger.info("SI keyword detected but document has main structure (abstract+introduction+results), treating as main")
                    break
                return "supplementary"

        title_candidates = [
            self.data.get("title", ""),
            getattr(getattr(self, "json_path", None), "stem", ""),
            self.data.get("file name", ""),
        ]
        title = ""
        for tc in title_candidates:
            if tc and len(str(tc)) > 10:
                title = str(tc)
                break
        if title and self._detect_review(title):
            return "review"
        if title and self._detect_communication(title):
            return "communication"

        return "main"

    def _has_main_document_structure(self) -> bool:
        section_names = set()
        for block in getattr(self, "blocks", []):
            kind = block.get("kind", "")
            if kind == "heading":
                section = block.get("section", "")
                if section:
                    section_names.add(section)
        main_indicators = {"abstract", "introduction", "results", "results_like", "experimental"}
        return len(section_names & main_indicators) >= 3

    def _detect_supplementary_atlas(self) -> bool:
        """
        检测是否为"图册型 Supplementary Information 文献"（supplementary_atlas）。
        
        触发信号（基于泛化模式，不硬编码具体论文名）：
        1. 首页或前几页出现: Supporting Information / Supplementary Information
        2. 前2-3页出现: Table of contents
        3. 连续多页出现: Supplementary Figure N / Supplementary Table N
        4. 图页占比高、caption密度高、连续图注页明显
        5. 正常 research article 的 abstract/introduction/results 结构弱
        """
        if self.document_kind != "supplementary":
            return False
        
        atlas_cfg = self.config.get("supplementary_atlas", {})
        page_range = atlas_cfg.get("toc_detection_page_range", 3)
        entry_threshold = atlas_cfg.get("toc_entry_threshold", 4)
        
        page_stats = {
            "toc_heading_count": 0,
            "supplementary_figure_entries": 0,
            "supplementary_table_entries": 0,
            "total_pages_with_entries": 0,
            "pure_morphology_entries": 0,
        }
        pages_checked = 0
        
        pure_morphology_keywords = [
            r"(?i)\bSEM\b", r"(?i)\bTEM\b", r"(?i)\bHAADF\b",
            r"(?i)\b(representative|fresh|as-prepared)",
        ]
        
        for elem in self._iter_layout_items():
            page_num = elem.get("page number", 1)
            if page_num > page_range:
                break
            pages_checked = max(pages_checked, page_num)
            
            content = self._normalize_text(elem.get("content", ""))
            if not content:
                continue
            
            # 检测 TOC 标题
            if self._is_toc_heading(content):
                page_stats["toc_heading_count"] += 1
            
            # 检测 Supplementary Figure/Table 条目
            if re.match(r'(?i)^supplementary\s+figure', content):
                page_stats["supplementary_figure_entries"] += 1
                page_stats["total_pages_with_entries"] += 1
                # 检测是否为纯形态学图注
                if any(re.search(pat, content) for pat in pure_morphology_keywords):
                    page_stats["pure_morphology_entries"] += 1
            
            if re.match(r'(?i)^supplementary\s+table', content):
                page_stats["supplementary_table_entries"] += 1
                page_stats["total_pages_with_entries"] += 1
        
        # atlas判定逻辑（基于泛化模式）
        is_atlas = False
        
        # 条件2: 前几页有 TOC
        if page_stats["toc_heading_count"] > 0:
            is_atlas = True
        
        # 条件3: 连续多页出现大量 Supplementary Figure/Table 条目
        if (page_stats["supplementary_figure_entries"] >= 10 or 
            page_stats["supplementary_table_entries"] >= 5):
            is_atlas = True
        
        # 条件4: 图注条目数量超过阈值
        if page_stats["supplementary_figure_entries"] >= entry_threshold:
            is_atlas = True
        
        # 额外验证: 页数>=30说明是长SI文档
        total_pages = self.data.get("number of pages", 0)
        if total_pages >= 30 and page_stats["supplementary_figure_entries"] >= 5:
            is_atlas = True
        
        if is_atlas:
            logger.info("supplementary_atlas detected: %s", page_stats)
        
        return is_atlas

    def _detect_heading_section(self, text: str) -> str:
        normalized = self._normalize_heading_token_spaces(text).lstrip("■ ").strip()
        heading_patterns = {
            "abstract": [
                r"(?i)^abstract\b",
            ],
            "experimental": [
                r"(?i)^experimental section\b",
                r"(?i)^experimental\b",
                r"(?i)^materials? and methods?\b",
                r"(?i)^methodology\b",
                r"(?i)^synthesis and characterization\b",
                r"(?i)^materials?\b",
            ],
            "results": [
                r"(?i)^results?(?: and discussion)?\b",
                r"(?i)^results & discussion\b",
                r"(?i)^results and analysis\b",
            ],
            "results_like": [
                r"(?i)^discussion\b",
                r"(?i)^discussion and conclusion\b",
            ],
            "conclusion": [
                r"(?i)^conclusions?\b",
            ],
            "metadata": [
                r"(?i)^article info\b",
                r"(?i)^keywords?\b",
            ],
            "backmatter": [
                r"(?i)^just accepted\b",
                r"(?i)^supporting information\b",
                r"(?i)^supplementary information\b",
                r"(?i)^associated content\b",
                r"(?i)^author information\b",
                r"(?i)^acknowledg",
                r"(?i)^references?\b",
            ],
        }
        for section, patterns in heading_patterns.items():
            if any(re.match(pattern, normalized) for pattern in patterns):
                return section
        return self._detect_section(normalized)

    def _is_abstract_start(self, text: str) -> bool:
        return bool(re.match(r"(?i)^abstract\s*:", self._normalize_heading_token_spaces(text)))

    def _normalize_scientific_notation(self, text: str) -> str:
        sup_map = {
            '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4',
            '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9', '⁻': '-'
        }
        def convert_match(m):
            base = m.group(1)
            exp_raw = m.group(2)
            exp_clean = ''.join(sup_map.get(c, c) for c in exp_raw).lstrip('^')
            try:
                value = float(base) * (10 ** int(exp_clean))
                if abs(value) < 1e-3 or abs(value) > 1e4:
                    return f"{value:e}".replace("e+0", "e").replace("e-0", "e-")
                return str(value)
            except (ValueError, OverflowError):
                return m.group(0)
        return re.sub(
            r'(\d+(?:\.\d+)?)\s*[×*]\s*10\s*([⁻⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+|[+-]?\d+)',
            convert_match,
            text,
        )

    def _split_sentences(self, text: str) -> List[str]:
        """将文本拆分为句子（基于规则，附带缩写保护）"""
        protected = re.sub(
            r"(?i)\b(Fig|Figs?|Eq|Eqs?|e\.g|i\.e|al|vs|Dr|Prof|et al|No|vol|Vols?|approx|ca|cf|resp|ref|refs)\.",
            lambda m: m.group(1) + "<DOT>",
            text,
        )
        sentences = re.split(r"(?<=[.!?;])\s+(?=[A-Z\"'\(\[\d])", protected)
        return [s.replace("<DOT>", ".").strip() for s in sentences if len(s.strip()) > 5]

    # ---------- 评分核心 ----------
    def _calculate_sentence_score(self, text: str, section: str) -> float:
        score = 0.0
        text_lower = text.lower()
        weights = getattr(self, "keyword_weights_lower", self.config["keyword_weights"])

        if self._keyword_pattern is not None:
            for match in self._keyword_pattern.finditer(text_lower):
                kw = match.group(0).lower()
                w = weights.get(kw)
                if w is not None:
                    score += w
        else:
            for kw, w in weights.items():
                if kw in ("numeric_with_unit", "range"):
                    continue
                if kw in text_lower:
                    score += w

        self._ensure_compiled_patterns()
        if self._COMPILED_NUMERIC_UNIT_PATTERN.search(text):
            score += weights.get("numeric_with_unit", 3.0)

        if self._COMPILED_RANGE_PATTERN.search(text):
            score += weights.get("range", 2.0)

        section_factor = self.config["section_boost"].get(section, 1.0)
        score *= section_factor

        length = len(text)
        if length < self.config["min_sentence_length"]:
            score *= 0.5
        elif length > self.config["max_sentence_length"]:
            score *= 0.8

        return round(score, 2)

    def _classify_block_kind(self, elem: Dict[str, Any], text: str) -> str:
        elem_type = elem.get("type", "paragraph")
        if elem_type == "heading":
            return "metadata" if str(elem.get("source", "")).lower() == "doctitle" else "heading"
        if elem_type in ("image", "picture"):
            return "figure"
        if self._parse_caption_label(text):
            return "caption"
        return "paragraph"

    def _is_junk_title(self, title: Optional[str]) -> bool:
        normalized = self._normalize_heading_token_spaces(title or "")
        if not normalized:
            return True

        junk_title_patterns = [
            r"(?i)^journal of\b",
            r"(?i)^journal\b",
            r"(?i)^volume\s+\d+(\s+number\s+\d+)?\b",
            r"(?i)^vol\.?\s*\d+\b",
            r"(?i)^issue\s+\d+\b",
            r"(?i)^pages?\s+\d+",
            r"(?i)^contents lists available at sciencedirect\b",
            r"(?i)^available online at\b",
            r"(?i)^sciencedirect\b",
            r"(?i)^chemcomm\b",
            r"(?i)^analyst\b",
            r"(?i)^chemical engineering journal\b",
            r"(?i)^article$",
            r"(?i)^paper$",
            r"(?i)^bad(?:\s+top-level)?\s+title$",
            r"(?i)^untitled$",
            r"(?i)^access$",
            r"(?i)^read online$",
            r"(?i)^metrics? & more$",
            r"(?i)^article recommendations$",
            r"(?i)^supporting information$",
            r"(?i)^subscriber access provided\b",
            r"(?i)^view article online\b",
            r"(?i)^view journal\b",
            r"(?i)^downloaded from\b",
            r"(?i)^just accepted(?: manuscript)?$",
            r"(?i)^highlights?$",
            r"(?i)^graphical abstract$",
            r"(?i)^article info$",
            r"(?i)^keywords?:?$",
            r"(?i)^abstract$",
            r"(?i)^[a-z]{1,6}\d{5,}\s+\d+\.\.\d+$",
            r"(?i)^[a-z0-9]{6,}\s+\d+\.\.\d+$",
        ]
        if any(re.match(pattern, normalized) for pattern in junk_title_patterns):
            return True

        if normalized.upper() in {"ARTICLE", "PAPER"}:
            return True
        if re.search(r"(?i)\b(?:https?://|www\.|pubs\.acs\.org|sciencedirect|elsevier\.com|rsc\.li)\b", normalized):
            return True
        if re.search(r"(?i)\b(?:volume|number|pages|issn)\b", normalized) and len(normalized.split()) <= 12:
            return True
        if re.search(r"(?i)\b(?:doi\s*:|received\b|accepted\b|published\b|corresponding authors?\b|e-mail addresses?\b)\b", normalized):
            return True
        if self._looks_like_author_info(normalized):
            return True
        if re.fullmatch(r"[A-Z](?:\s+[A-Z]){2,}", normalized):
            return True
        if len(normalized) < 8:
            return True
        return False

    def _clean_title_candidate_text(self, text: str) -> str:
        normalized = self._normalize_heading_token_spaces(text)
        normalized = normalized.strip(" •†‡*#|")
        normalized = re.sub(r"\s*[†‡*#]+\s*$", "", normalized).strip()
        return normalized

    def _looks_like_title_candidate(self, elem: Dict[str, Any], title: str) -> bool:
        normalized = self._clean_title_candidate_text(title)
        if self._is_junk_title(normalized):
            return False

        elem_type = str(elem.get("type", "")).lower()
        if elem_type == "heading":
            return True
        if elem.get("page number", 1) != 1:
            return False
        if elem_type != "paragraph":
            return False
        if len(normalized) < 20 or len(normalized) > 220:
            return False
        if len(normalized.split()) < 4 or len(normalized.split()) > 28:
            return False
        if re.search(r"(?i)^(abstract|keywords?|graphical abstract|highlights?)\b", normalized):
            return False
        if re.search(r"(?i)\b(herein|in this article|in this study|we report|we demonstrate)\b", normalized):
            return False
        if normalized.endswith((".", ";", ":")):
            return False
        return True

    def _score_title_candidate(self, elem: Dict[str, Any], title: str, ordinal: int = 0) -> float:
        normalized = self._clean_title_candidate_text(title)
        if self._is_junk_title(normalized):
            return float("-inf")

        score = 0.0
        page = elem.get("page number", 1)
        source = str(elem.get("source", "")).lower()
        level = str(elem.get("level", "")).lower()
        elem_type = str(elem.get("type", "")).lower()

        if page == 1:
            score += 8.0
        else:
            score -= min(page, 4)
        if elem_type == "heading":
            score += 3.0
        elif elem_type == "paragraph":
            score += 0.5
        elif elem_type == "metadata_title":
            score += 2.0
        if source == "data.title":
            score += 4.0
        if source == "doctitle":
            score += 2.0
        if level == "title":
            score += 3.0
        if level == "subtitle":
            score += 2.5
        elif level == "doctitle":
            score += 1.0
        score += max(0.0, 4.0 - ordinal * 0.35)

        word_count = len(normalized.split())
        if 6 <= word_count <= 22:
            score += 3.0
        elif 4 <= word_count <= 28:
            score += 1.5
        elif word_count >= 3:
            score += 0.5
        else:
            score -= 2.0

        if 45 <= len(normalized) <= 180:
            score += 2.5
        elif 25 <= len(normalized) <= 220:
            score += 1.5
        elif len(normalized) > 220:
            score -= 1.5

        if re.search(r"[a-z]", normalized) and re.search(r"[A-Z]", normalized):
            score += 0.5
        if re.search(r"[0-9α-ωΑ-Ω+\-()/]", normalized):
            score += 0.5
        if re.match(r"(?i)^\d+(\.\d+)?\s+", normalized):
            score -= 3.0
        if re.search(r"\b[a-zA-Z]\s+[a-zA-Z]{2,}\s+[a-zA-Z]{2,}", normalized):
            score -= 2.5
        if normalized.endswith((".", ";", ":")):
            score -= 2.5
        if re.search(r"(?i)\b(nanozyme|nanozymes|nanoparticles?|nanosheets?|nanotubes?|catalyst|enzyme-like|oxidase|peroxidase|catalase|therapy|sensing|detection|photodynamic|carbon|metal|single atom|activity)\b", normalized):
            score += 2.0
        if re.search(r"(?i)\b(cite this|doi|received|accepted|published|downloaded from|subscriber access|view article online|journal homepage|contents lists available|science direct|sciencedirect)\b", normalized):
            score -= 8.0
        if re.search(r"(?i)\b(volume|number|pages|issn)\b", normalized):
            score -= 8.0
        if self._looks_like_author_info(normalized):
            score -= 8.0
        heading_section = self._detect_heading_section(normalized)
        if heading_section != "unknown":
            if heading_section == "backmatter" and self.document_kind == "supplementary":
                si_title_prefix = re.match(r"(?i)^(?:supporting|supplementary)\s+(?:information|material|data)\b", normalized)
                if si_title_prefix and len(normalized) > si_title_prefix.end() + 10:
                    pass
                else:
                    score -= 4.0
            else:
                score -= 4.0

        return score

    def _extract_document_metadata(self) -> Dict[str, Any]:
        kids = list(self._iter_layout_items())
        data = getattr(self, "data", {})
        top_level_title = self._clean_title_candidate_text(data.get("title", "") or "")

        raw_candidates: List[Dict[str, Any]] = []
        if top_level_title:
            raw_candidates.append(
                {
                    "elem": {"type": "metadata_title", "page number": 1, "source": "data.title", "level": "metadata"},
                    "title": top_level_title,
                    "origin": "data.title",
                    "page": 1,
                }
            )

        page1_ordinal = 0
        for elem in kids:
            if elem.get("page number", 1) != 1:
                continue
            content = self._clean_title_candidate_text(elem.get("content", "") or "")
            if not content:
                continue
            if not self._looks_like_title_candidate(elem, content):
                continue
            page1_ordinal += 1
            raw_candidates.append(
                {
                    "elem": elem,
                    "title": content,
                    "origin": f"page1.{elem.get('type', 'unknown')}:{elem.get('source') or elem.get('level') or 'plain'}",
                    "page": elem.get("page number", 1),
                    "ordinal": page1_ordinal,
                }
            )

        deduped_candidates: Dict[str, Dict[str, Any]] = {}
        title_candidates: List[Dict[str, Any]] = []
        for candidate in raw_candidates:
            title = candidate["title"]
            score = self._score_title_candidate(candidate["elem"], title, candidate.get("ordinal", 0))
            title_key = re.sub(r"[^a-z0-9]+", "", title.lower())
            candidate_info = {
                "origin": candidate["origin"],
                "page": candidate["page"],
                "score": round(score, 2) if score != float("-inf") else "junk",
                "title": title,
            }
            title_candidates.append(candidate_info)
            if score == float("-inf"):
                continue
            enriched = dict(candidate)
            enriched["score"] = score
            if title_key not in deduped_candidates or score > deduped_candidates[title_key]["score"]:
                deduped_candidates[title_key] = enriched

        scored_candidates = sorted(
            deduped_candidates.values(),
            key=lambda item: (item["score"], -item.get("page", 1), -item.get("ordinal", 0)),
            reverse=True,
        )
        selected_candidate = scored_candidates[0] if scored_candidates else None
        title = selected_candidate["title"] if selected_candidate else (top_level_title or data.get("title"))

        self._last_title_candidates = title_candidates
        self._last_selected_title_candidate = {
            "title": selected_candidate["title"],
            "origin": selected_candidate["origin"],
            "score": round(selected_candidate["score"], 2),
        } if selected_candidate else None

        logger.info("title candidates: %s", title_candidates)
        logger.info("selected article title: %s", self._last_selected_title_candidate or title)

        doi = self._extract_doi(data)
        year = self._extract_year(data)
        author = self._extract_author(data)
        journal = self._extract_journal(data)
        if self.document_kind == "supplementary" and year:
            try:
                y = int(year)
                if y < 1950 or y > 2030:
                    year = ""
            except (ValueError, TypeError):
                year = ""

        return {
            "source_file": data.get("file name") or data.get("file_name") or self.pdf_stem,
            "file_name": data.get("file name") or data.get("file_name"),
            "title": title,
            "author": author,
            "journal": journal,
            "pages": data.get("number of pages"),
            "doi": doi,
            "year": year,
            "is_supplementary": self.document_kind == "supplementary",
            "document_kind": self.document_kind,
            "schema_version": "nanozyme.v1",
            "parser_format": "kids_layout_stream",
            "extraction_mode": self.extraction_mode,
        }

    def _iter_front_matter_items(self, max_page: int = 2):
        for item in self._iter_layout_items():
            page = item.get("page number", 1)
            if page > max_page:
                break
            yield item

    def _metadata_text_key(self, text: Any) -> str:
        if text is None:
            return ""
        return re.sub(r"[^a-z0-9]+", "", str(text).lower())

    def _clean_author_candidate(self, author: Any) -> str:
        if not isinstance(author, str):
            return ""
        author = self._normalize_text(author)
        author = re.sub(r'\s*\[[^\]]+\]', '', author)
        author = re.sub(r'[\*†‡§#¶]+', '', author)
        author = re.sub(r'\s*,\s*,\s*', ', ', author)
        author = re.sub(r'\bORCID\b.*$', '', author, flags=re.IGNORECASE)
        author = re.sub(r'[;,]\s*$', '', author)
        author = re.sub(r'\s+,', ',', author)
        author = re.sub(r'\s{2,}', ' ', author)
        capitalized_seen = 0
        cut_pos = None
        for match in re.finditer(r"\b[A-Za-z][A-Za-z'’.\-]*\b", author):
            token = match.group(0)
            if token[0].isupper():
                capitalized_seen += 1
                continue
            if capitalized_seen >= 4 and len(token) > 3 and token.lower() not in {"and", "et", "al", "de", "van", "von", "with"}:
                cut_pos = match.start()
                break
        if cut_pos is not None:
            author = author[:cut_pos].rstrip(" ,;")
        return author.strip(" ,;")

    def _looks_like_author_line(self, text: str) -> bool:
        cleaned = self._clean_author_candidate(text)
        if not cleaned or len(cleaned) < 8 or len(cleaned) > 260:
            return False
        lowered = cleaned.lower()
        if re.match(r"^[A-Z][A-Za-z'’.\-]+(?:\s+[A-Z][A-Za-z'’.\-]+)?\s+et\s+al\.?$", cleaned):
            return True
        if re.search(r'(?i)\b(?:doi|received|accepted|published|available|copyright|abstract|introduction)\b', cleaned):
            return False
        if re.search(r'(?i)\b(?:college|university|department|institute|academy|laboratory|school of|faculty of|hospital)\b', cleaned):
            return False
        if re.search(r'https?://|@', cleaned):
            return False
        if re.search(r'\b(?:19|20)\d{2}\b', cleaned):
            return False
        if re.search(r'(?i)\b(?:observed|show(?:s|n)?|report(?:ed)?|investigat(?:e|ed)|perform(?:ed)?|catalyz(?:e|ed)|were|was|is|are|demonstrat(?:e|ed))\b', cleaned):
            return False
        capitalized = re.findall(r"\b[A-Z][A-Za-z'’.\-]+\b", cleaned)
        if len(capitalized) < 3:
            return False
        word_tokens = re.findall(r"[A-Za-z][A-Za-z'’.\-]+", cleaned)
        lowercase_words = [
            token for token in word_tokens
            if token[0].islower() and token.lower() not in {"and", "et", "al", "de", "van", "von", "da", "del"}
        ]
        if len(lowercase_words) > max(2, len(word_tokens) // 5):
            return False
        if not ("," in cleaned or re.search(r'\band\b', lowered)):
            return False
        if cleaned.endswith(".") and "et al" not in lowered:
            return False
        return True

    def _is_valid_parser_author(self, author: str, page_author: str) -> bool:
        if not author:
            return False
        lowered = author.lower()
        compact = self._metadata_text_key(author)
        if len(author) < 6:
            return False
        if not self._looks_like_author_line(author):
            return False
        if re.search(r'(?i)\b(?:adobe|acrobat|administrator|admin|author|creator|default|desktop|editor|lenovo|microsoft|office|scanner|user|windows)\b', author):
            return False
        if self.document_kind == "supplementary" and re.search(r'(?i)\b(?:college|university|department|institute|academy|laboratory|school of|faculty of)\b', author):
            return False
        tokens = re.findall(r"[A-Za-z][A-Za-z'’.\-]+", author)
        if len(tokens) <= 2 and len(author) <= 20:
            return False
        if len(tokens) <= 3 and not ("," in author or " and " in lowered) and len(author) <= 28:
            return False
        if page_author and self._metadata_text_key(page_author) != compact:
            if len(tokens) <= 4 or len(author) < 40:
                return False
        return True

    def _looks_like_author_continuation(self, text: str) -> bool:
        cleaned = self._clean_author_candidate(text)
        if not cleaned or len(cleaned) > 120:
            return False
        if re.search(r'(?i)\b(?:school|university|department|institute|laboratory|email|doi|received|accepted|figure|table)\b', cleaned):
            return False
        if re.search(r'https?://|@', cleaned):
            return False
        capitalized = re.findall(r"\b[A-Z][A-Za-z'’.\-]+\b", cleaned)
        return len(capitalized) >= 2

    def _extract_author(self, data: Dict) -> str:
        author_candidates: List[Dict[str, Any]] = []
        front_items = list(self._iter_front_matter_items(2))
        for ordinal, item in enumerate(front_items, start=1):
            content = item.get("content", "")
            if not isinstance(content, str):
                continue
            page = item.get("page number", 1)
            if page > 1:
                continue
            if not self._looks_like_author_line(content):
                continue
            cleaned = self._clean_author_candidate(content)
            if ordinal < len(front_items):
                next_item = front_items[ordinal]
                if next_item.get("page number", 1) == page:
                    next_content = next_item.get("content", "")
                    if isinstance(next_content, str) and self._looks_like_author_continuation(next_content):
                        cleaned = self._clean_author_candidate(f"{cleaned} {next_content}")
            capitalized = len(re.findall(r"\b[A-Z][A-Za-z'’.\-]+\b", cleaned))
            score = 100 - ordinal + 20 + min(capitalized, 10)
            if self._looks_like_author_info(cleaned):
                score += 8
            author_candidates.append(
                {
                    "value": cleaned,
                    "source": f"page{page}",
                    "score": score,
                }
            )
        if not author_candidates:
            for ordinal, item in enumerate(front_items, start=1):
                content = item.get("content", "")
                if not isinstance(content, str):
                    continue
                page = item.get("page number", 1)
                if page != 2:
                    continue
                cleaned = self._clean_author_candidate(content)
                if len(cleaned) > 80 or re.search(r'(?i)\b(?:figure|table|supplementary)\b', cleaned):
                    continue
                if not self._looks_like_author_line(cleaned):
                    continue
                author_candidates.append(
                    {
                        "value": cleaned,
                        "source": f"page{page}",
                        "score": 40 - ordinal,
                    }
                )

        author_candidates.sort(key=lambda item: item["score"], reverse=True)
        page_author = author_candidates[0]["value"] if author_candidates else ""
        parser_author = self._clean_author_candidate(data.get("author"))
        parser_author_valid = self._is_valid_parser_author(parser_author, page_author)
        selected = page_author or (parser_author if parser_author_valid else "")
        self._last_author_candidates = author_candidates
        self._last_author_source = "page_text" if page_author else ("parser metadata" if parser_author_valid else None)
        logger.info("author candidates: %s", author_candidates[:8])
        logger.info("selected author: %s (%s)", selected, self._last_author_source or "none")
        return selected

    def _try_get_main_article_year(self) -> str:
        if self.document_kind != "supplementary":
            return ""
        main_stem = self.pdf_stem.replace(" SI", "").replace("_SI", "").strip()
        candidate_path = self.json_path.parent / f"{main_stem}.json"
        if not candidate_path.exists():
            return ""
        try:
            helper = self.__class__(
                str(candidate_path),
                images_root=str(self.images_root),
                output_root=str(self.output_root),
                rulebook_path=str(self.rulebook_path),
            )
            helper.document_kind = "main"
            return helper._extract_year(helper.data)
        except Exception:
            return ""

    def _extract_journal(self, data: Dict) -> str:
        for item in self._iter_front_matter_items(2):
            content = item.get("content", "")
            if not isinstance(content, str):
                continue
            patterns = [
                r'^([A-Z][A-Za-z\.\s]+?)\s*(?:19|20)\d{2}\s*,',
                r'([A-Z][A-Za-z\.\s]+?)\s*(?:19|20)\d{2}\s*,\s*\d+\s*,\s*\d+',
                r'([A-Z][A-Za-z\.\s&]+?)\s+(?:19|20)\d{2}\s*,\s*\d+\s*[-–]',
            ]
            for pattern in patterns:
                m = re.search(pattern, content)
                if m:
                    candidate = m.group(1).strip()
                    if 3 < len(candidate) < 60 and not re.match(r'^(?:the|and|for|with|from)\b', candidate, re.IGNORECASE):
                        return candidate
        journal = data.get("journal") or data.get("Journal")
        if journal and isinstance(journal, str):
            return journal
        return ""

    def _clean_doi(self, raw: str) -> str:
        normalized = self._normalize_text(raw)
        normalized = normalized.replace("https:// doi.org/", "https://doi.org/")
        normalized = normalized.replace("http:// doi.org/", "http://doi.org/")
        normalized = re.sub(r"\s*/\s*", "/", normalized)
        normalized = re.sub(r"\s+", "", normalized)
        return normalized.rstrip(".,;)]}>")

    def _extract_doi_from_text(self, text: str) -> Optional[str]:
        if not isinstance(text, str) or not text.strip():
            return None
        normalized = self._normalize_text(text)
        normalized = normalized.replace("https:// doi.org/", "https://doi.org/")
        normalized = normalized.replace("http:// doi.org/", "http://doi.org/")

        patterns = [
            re.compile(r'(?:(?:https?://)?(?:dx\.)?doi\.org/|doi\s*[:=]\s*)(10\.\d{4,9}/\S+)', re.IGNORECASE),
            re.compile(r'pubs\.acs\.org/(?:doi/)?(10\.\d{4,9}/\S+)', re.IGNORECASE),
            re.compile(r'(10\.\d{4,9}/\S+)', re.IGNORECASE),
        ]
        for pattern in patterns:
            match = pattern.search(normalized)
            if not match:
                continue
            candidate = self._clean_doi(match.group(1))
            if re.search(r'/[A-Za-z0-9]', candidate):
                return candidate
        return None

    def _extract_doi(self, data: Dict) -> str:
        doi_candidates: List[Dict[str, Any]] = []

        top_level_doi = data.get("doi") or data.get("DOI") or data.get("identifier")
        if isinstance(top_level_doi, str):
            candidate = self._extract_doi_from_text(top_level_doi)
            if candidate:
                doi_candidates.append({
                    "doi": candidate,
                    "source": "parser metadata",
                    "page": 0,
                    "priority": 40,
                })

        for index, item in enumerate(self._iter_layout_items(), start=1):
            content = item.get("content", "")
            candidate = self._extract_doi_from_text(content)
            if not candidate:
                continue
            page = item.get("page number", 1)
            normalized = self._normalize_text(content)
            if re.search(r'(?i)\bdoi\s*[:=]', normalized):
                source = "DOI line"
                source_priority = 120
            elif re.search(r'(?i)\bcite this\b', normalized):
                source = "citation line"
                source_priority = 100
            elif re.search(r'(?i)doi\.org|pubs\.acs\.org/(?:doi/)?10\.', normalized):
                source = "url"
                source_priority = 90
            else:
                source = "page text"
                source_priority = 65
            doi_candidates.append({
                "doi": candidate,
                "source": source,
                "page": page,
                "priority": source_priority + (20 if page == 1 else 10 if page == 2 else 0),
                "ordinal": index,
            })

        best_candidate = None
        for candidate in sorted(
            doi_candidates,
            key=lambda item: (item["priority"], -item.get("page", 0), -item.get("ordinal", 0)),
            reverse=True,
        ):
            best_candidate = candidate
            break

        self._last_doi_candidates = doi_candidates
        self._last_doi_source = best_candidate["source"] if best_candidate else None
        logger.info("doi candidates: %s", doi_candidates[:12])
        logger.info("selected doi: %s (%s)", best_candidate["doi"] if best_candidate else "", self._last_doi_source or "none")
        return best_candidate["doi"] if best_candidate else ""

    def _extract_year(self, data: Dict) -> str:
        """从 parser 数据中提取发表年份。"""
        year_candidates: List[Dict[str, Any]] = []
        for ordinal, item in enumerate(self._iter_front_matter_items(2), start=1):
            content = item.get("content", "")
            if not isinstance(content, str):
                continue
            normalized = self._normalize_text(content)
            page = item.get("page number", 1)
            matches = re.findall(r'\b(?:19|20)\d{2}\b', normalized)
            if not matches:
                continue
            priority = 0
            if re.search(r'(?i)\b(received|accepted|published|available online|copyright|doi)\b', normalized):
                priority = 120
            elif re.search(r'(?i)\b(?:j\.|journal|chem\.|mater\.|commun\.|science|letters?)\b', normalized) and re.search(r'\b(?:19|20)\d{2}\s*,', normalized):
                priority = 110
            elif page <= 2:
                priority = 70
            if priority:
                year_candidates.append(
                    {
                        "year": matches[0],
                        "source": f"page{page}",
                        "priority": priority - ordinal,
                    }
                )
        for key in ("year", "publication_year", "published", "date"):
            val = data.get(key)
            if val and isinstance(val, str):
                m = re.search(r'\b(19|20)\d{2}\b', val)
                if m:
                    year_candidates.append(
                        {
                            "year": m.group(0),
                            "source": f"parser:{key}",
                            "priority": 20,
                        }
                    )
        best_candidate = None
        for candidate in sorted(year_candidates, key=lambda item: item["priority"], reverse=True):
            best_candidate = candidate
            break
        if not best_candidate:
            main_year = self._try_get_main_article_year()
            if main_year:
                best_candidate = {"year": main_year, "source": "main_article_fallback", "priority": 15}
        self._last_year_candidates = year_candidates
        logger.info("year candidates: %s", year_candidates[:10])
        logger.info("selected year: %s (%s)", best_candidate["year"] if best_candidate else "", best_candidate["source"] if best_candidate else "none")
        return best_candidate["year"] if best_candidate else ""

    def _looks_like_figure_ocr(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False

        short_axis_patterns = [
            r"(?i)^\[s\]\s*\(.*\)$",
            r"(?i)^wavenumber(\s*\(.*\))?$",
            r"(?i)^binding energy(\s*\(.*\))?$",
            r"(?i)^intensity(\s*\(.*\))?$",
            r"(?i)^absorbance(\s*\(.*\))?$",
            r"(?i)^raman shift(\s*\(.*\))?$",
            r"(?i)^time(\s*\(.*\))?$",
            r"(?i)^\d+(\.\d+)?\s*(nm|mm|cm|mM|uM|μM|eV|s|min|h)$",
            r"(?i)^[A-Za-z]{1,3}\s*\d*$",
            r"^[\d\.\-\+\(\)\[\]\s/%]+$",
        ]
        if any(re.match(pattern, normalized) for pattern in short_axis_patterns):
            return True

        tokens = normalized.split()
        if len(tokens) <= 4:
            short_token_count = sum(1 for token in tokens if len(token) <= 4 or re.search(r"\d", token))
            if short_token_count == len(tokens):
                return True

        alnum_ratio = len(re.findall(r"[A-Za-z0-9]", normalized)) / max(len(normalized), 1)
        if len(normalized) <= 25 and alnum_ratio > 0.6 and not re.search(r"[.!?]$", normalized):
            return True

        return False

    def _is_incomplete_sentence(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return True

        if re.match(r"^\s*(\[\d+(?:,\d+)*\]|\d+\s*[-,]\s*\d+)", normalized) and len(normalized) < 160:
            return True

        text_lower = normalized.lower()
        if re.search(r'[a-z]{2,}\d', text_lower):
            return False

        if len(normalized) < 30 and not re.search(r"(?i)\b(km|vmax|kcat|tmb|abts|opd|sers|uv-?vis|nanozyme|detection\s+limit|linear\s+range|specificity|sensitivity|selectivity|k\s*cat|k\s*m|k\s*i)\b", normalized):
            return True

        if (
            len(normalized.split()) <= 8
            and not re.search(r"[.!?]$", normalized)
            and not re.search(r"(?i)\b(km|vmax|kcat|tmb|abts|opd|sers|uv-?vis|nanozyme|detection\s+limit|linear\s+range|specificity|sensitivity|selectivity)\b", normalized)
        ):
            return True

        trailing_fragment_patterns = [
            r"(?i)\b(and|or|with|for|to|of|than|using)\s*$",
            r"(?i)\bshowed a\s*$",
        ]
        return any(re.search(pattern, normalized) for pattern in trailing_fragment_patterns)

    def _drop_before_scoring_text(self, text: str) -> Optional[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return "empty"

        boilerplate_patterns = [
            r"(?i)^contents lists available at sciencedirect\b",
            r"(?i)^journal homepage\b",
            r"(?i)^article history\b",
            r"(?i)^available online\b",
            r"(?i)^published by\b",
            r"(?i)^recommended articles\b",
        ]
        if any(re.match(pattern, normalized) for pattern in boilerplate_patterns):
            return "boilerplate"
        if self._looks_like_supplementary_toc_text(normalized):
            return "supplementary_toc"
        if self._looks_like_author_info(normalized):
            return "author_info"
        if self._looks_like_reference_tail(normalized):
            return "reference_tail"
        if self._is_reference_entry(normalized):
            return "reference_entry"
        if self._looks_like_figure_ocr(normalized):
            return "figure_ocr_fragment"
        if self._is_incomplete_sentence(normalized):
            return "incomplete"
        return None

    def _drop_before_scoring(self, sentence: SentenceInfo) -> Optional[str]:
        if sentence.source_kind == "figure_ocr":
            return "figure_ocr_fragment"
        title = self._normalize_text(self.paper_metadata.get("title", "")) if isinstance(self.paper_metadata, dict) else ""
        if title and sentence.page > 1:
            normalized = self._normalize_text(sentence.text)
            if normalized == title or (len(normalized) >= max(20, int(len(title) * 0.75)) and normalized in title):
                return "repeated_title"
        return self._drop_before_scoring_text(sentence.text)

    def _has_signal(self, text: str, patterns: List[str]) -> bool:
        return any(re.search(pattern, text) for pattern in patterns)

    def _selection_roles(self) -> Tuple[str, ...]:
        return (
            "paper",
            "system",
            "activity",
            "assay",
            "kinetics",
            "structure",
            "mechanism",
            "comparison",
            "application",
            "supplementary",
        )

    def _looks_like_supplementary_toc_text(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if self.document_kind != "supplementary" or not normalized:
            return False
        if self._is_toc_heading(normalized):
            return True
        if self._is_supplementary_toc_entry(normalized):
            return not re.search(
                r"(?i)\b(is|are|was|were|shows?|showed|indicates?|demonstrates?|reveals?|describes?|measured|performed|obtained)\b",
                normalized,
            )
        toc_fragment_patterns = [
            r"(?i)^(representative|kinetic|mass normalized|relative energies|energy profile|evaluation of relationship)\b",
            r"(?i)^(structural models|comparison between calculated and experimental|adsorption energies)\b",
            r"(?i)^(nitrogen adsorption[- ]desorption|pxrd patterns|magnetic measurements)\b",
        ]
        return len(normalized) < 220 and any(re.match(pattern, normalized) for pattern in toc_fragment_patterns)

    def _contains_formula_like_material_token(self, text: str) -> bool:
        return bool(
            re.search(r"\b[A-Za-z0-9()]+(?:[@/][A-Za-z0-9()\-]+)+\b", text)
            or re.search(r"\b[A-Z][a-z]?(?:[-–][A-Z][a-z]?\d+){1,3}\b", text)
            or re.search(r"\b(?:[A-Z][a-z]?\d+){2,}(?:[-/][A-Za-z0-9()]+)*\b", text)
        )

    def _retag_sentence_section(self, sentence: SentenceInfo) -> None:
        evidence_roles = {"system", "activity", "assay", "kinetics", "structure", "mechanism", "comparison", "application", "supplementary"}
        if not any(tag in sentence.value_tags for tag in evidence_roles):
            return

        method_patterns = [
            r"(?i)\b(prepared|synthesi[sz]ed|fabricated|loaded|embedded|encapsulated|doped|incubat(?:ed|ion)|stirred|centrifuged|washed)\b",
            r"(?i)\b(measured|recorded|acquired|collected|characterized|performed|monitored|obtained from)\b",
        ]
        if sentence.section == "introduction":
            if sentence.source_kind == "caption":
                sentence.section = "results_like"
            elif self._has_signal(sentence.text, method_patterns) and not any(
                tag in sentence.value_tags for tag in ("comparison", "application", "paper")
            ):
                sentence.section = "experimental"
            else:
                sentence.section = "results_like"
        elif sentence.section == "unknown" and sentence.source_kind == "caption":
            sentence.section = "results_like"

    def _tag_sentence(self, sentence: SentenceInfo) -> List[str]:
        text = self._normalize_text(sentence.text)
        text_lower = text.lower()
        tags: List[str] = []
        self._ensure_compiled_patterns()
        tp = self._COMPILED_TAG_PATTERNS

        if any(p.search(text) for p in tp["paper"]):
            tags.append("paper")
        if any(p.search(text) for p in tp["system"]) or (
            self._contains_formula_like_material_token(text)
            and tp["system_extra"].search(text)
        ):
            tags.append("system")
        if self._COMPILED_ENZYME_MENTION_PATTERN.search(text) or any(p.search(text) for p in tp["activity_extra"]):
            tags.append("activity")
        if any(p.search(text) for p in tp["assay"]):
            tags.append("assay")
        if any(p.search(text) for p in tp["kinetics"]):
            tags.append("kinetics")
        if any(p.search(text) for p in tp["structure"]):
            tags.append("structure")
        if any(p.search(text) for p in tp["mechanism"]):
            tags.append("mechanism")
        if any(p.search(text) for p in tp["comparison"]):
            tags.append("comparison")
        if any(p.search(text) for p in tp["application"]):
            tags.append("application")
        if self._COMPILED_SPECIFICITY_PATTERN.search(text):
            tags.extend(["activity", "mechanism", "comparison"])
        if self.document_kind == "supplementary" and not self._looks_like_supplementary_toc_text(text) and any(
            tag in tags for tag in self._selection_roles() if tag != "supplementary"
        ):
            tags.append("supplementary")

        if any(p.search(text_lower) for p in tp["background"]):
            tags.append("background")
        elif sentence.section in {"introduction", "abstract"} and not any(
            tag in tags for tag in self._selection_roles()
        ):
            tags.append("background")

        sentence.value_tags = list(dict.fromkeys(tags))
        self._retag_sentence_section(sentence)
        return sentence.value_tags

    def _extract_candidate_system_mentions(self, text: str, value_tags: Optional[List[str]] = None) -> List[str]:
        effective_tags = set(value_tags or [])
        if effective_tags == {"background"}:
            return []

        patterns = [
            r"(?i)\b[A-Za-z0-9\-()/]+(?:\s*[/]\s*[A-Za-z0-9\-()]+)*(?:\s+[A-Za-z0-9\-()]+){0,3}\s+(?:nanotubes?|nanoparticles?|nanosheets?|nanorods?|nanowires?|nanozymes?|nanofibers?)\b",
            r"(?i)\b[A-Za-z0-9\-()/]+(?:\s*[/]\s*[A-Za-z0-9\-()]+){0,2}\s+(?:carbon\s+dots?|C(?:arbon)?\s*Dots?|CDs)\b",
            r"(?i)\b[A-Za-z0-9\-()/]+(?:\s*[/]\s*[A-Za-z0-9\-()]+){0,2}\s+(?:MOF[- ]?\d+)\b",
            r"(?i)\b[A-Za-z0-9\-()/]+(?:\s*[/]\s*[A-Za-z0-9\-()]+)*(?:\s+[A-Za-z0-9\-()]+){0,2}\s+system\b",
            r"(?i)\b[A-Za-z0-9\-()/]+\s+(?:N-doped|N-dopant|nitrogen.doped)\s+(?:carbon|graphene|nanofibers?|nanotubes?)\b",
            r"(?i)\bMOF[- ]?\d+\s+(?:nanozyme|catalyst|composite)\b",
            r"(?i)\b(?:carbon\s+dots?|C(?:arbon)?\s*Dots?|CDs)\b",
            r"(?i)\b[A-Za-z0-9()]+(?:[@/][A-Za-z0-9()\-]+)+(?:\s+(?:nanozymes?|nanoparticles?|catalysts?|composites?|frameworks?|spheres?|dots?|gels?))?\b",
            r"(?i)\b(?:single[- ]atom|single atom|dual[- ]atom|binuclear|trinuclear)\s+[A-Za-z0-9\-()/]+\s+(?:catalysts?|nanozymes?|sites?|centers?)\b",
            r"(?i)\b[A-Z][a-z]?(?:[-–][A-Z][a-z]?\d+){1,3}\s+(?:sites?|centers?|motifs?)\b",
        ]
        bad_tokens = {"showed", "using", "only", "stronger", "weaker", "signal", "gave", "than", "before", "material", "based", "including", "containing"}
        mentions: List[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                candidate = match.group(0).strip(" ,.;:")
                candidate_tokens = {token.lower() for token in re.split(r'[\s/]+', candidate)}
                if len(candidate) < 6:
                    continue
                if candidate and not (candidate_tokens & bad_tokens) and candidate not in mentions:
                    mentions.append(candidate)
        return mentions

    def _assign_sentence_ids(self, sentences: List[SentenceInfo]) -> List[SentenceInfo]:
        for index, sentence in enumerate(sentences, start=1):
            sentence.sentence_id = f"S{index:04d}"
        return sentences

    def _reading_order_key(self, sentence: SentenceInfo) -> Tuple[int, int, str]:
        kid_seq = sentence.kid_ids[0] if sentence.kid_ids else 10**9
        return (sentence.page, kid_seq, sentence.text[:50])

    def _finalize_selected_sentences(self, sentences: List[SentenceInfo]) -> List[SentenceInfo]:
        finalized = sorted(sentences, key=self._reading_order_key)
        return self._assign_sentence_ids(finalized)

    def _build_chunk_contexts(self, chunks: List[List[SentenceInfo]]) -> List[Dict[str, Any]]:
        contexts: List[Dict[str, Any]] = []
        for index, chunk in enumerate(chunks, start=1):
            system_mentions: List[str] = []
            enzyme_mentions: List[str] = []
            substrate_mentions: List[str] = []
            application_mentions: List[str] = []
            has_kinetics = False
            has_material = False
            is_caption_chunk = False
            is_supplementary_chunk = self.document_kind == "supplementary"
            is_table_related = False
            figure_labels: List[str] = []
            signal_types: Set[str] = set()
            section_types: Set[str] = set()
            for sentence in chunk:
                system_mentions = self._merge_unique(system_mentions, self._extract_candidate_system_mentions(sentence.text, sentence.value_tags))
                enzyme_mentions = self._merge_unique(enzyme_mentions, sentence.candidate_enzyme_mentions)
                substrate_mentions = self._merge_unique(substrate_mentions, sentence.candidate_substrate_mentions)
                application_mentions = self._merge_unique(application_mentions, sentence.candidate_application_mentions)
                if sentence.contains_kinetics_signal:
                    has_kinetics = True
                if sentence.contains_material_signal:
                    has_material = True
                if sentence.source_kind == "caption":
                    is_caption_chunk = True
                if sentence.figure_label:
                    figure_labels.append(sentence.figure_label)
                if sentence.signal_type:
                    signal_types.add(sentence.signal_type)
                if sentence.section in ("experimental", "results", "results_like"):
                    section_types.add(sentence.section)
            chunk_text = " ".join(s.text for s in chunk)
            system_mentions, candidate_filter_stats = _filter_candidate_mentions(system_mentions, chunk_text)
            sections = sorted({sentence.section for sentence in chunk})
            primary_section = sections[0] if sections else "unknown"
            section_type = "results" if section_types & {"results", "results_like"} else ("experimental" if "experimental" in section_types else "other")
            contexts.append(
                {
                    "chunk_index": index - 1,
                    "chunk_id": f"chunk_{index:03d}",
                    "section": primary_section,
                    "section_type": section_type,
                    "is_caption": is_caption_chunk,
                    "is_table_related": is_table_related,
                    "is_supplementary": is_supplementary_chunk,
                    "pages": sorted({sentence.page for sentence in chunk}),
                    "sections": sections,
                    "candidate_system_mentions": system_mentions,
                    "candidate_enzyme_mentions": enzyme_mentions,
                    "candidate_substrate_mentions": substrate_mentions,
                    "candidate_application_mentions": application_mentions,
                    "contains_kinetics_signal": has_kinetics,
                    "contains_numeric_signal": any(sentence.contains_numeric for sentence in chunk),
                    "contains_material_signal": has_material,
                    "signal_types": sorted(signal_types),
                    "figure_labels": sorted(set(figure_labels)),
                    "sentence_ids": [sentence.sentence_id for sentence in chunk],
                    "candidate_filter_stats": candidate_filter_stats,
                }
            )
        return contexts

    def _iter_layout_items(self, items: Optional[List[Dict[str, Any]]] = None):
        source_items = getattr(self, "kids", []) if items is None else items
        for elem in source_items or []:
            if not isinstance(elem, dict):
                continue
            nested_kids = elem.get("kids")
            if isinstance(nested_kids, list) and nested_kids:
                yield from self._iter_layout_items(nested_kids)
                continue
            rows = elem.get("rows")
            if isinstance(rows, list) and rows:
                for row in rows:
                    if isinstance(row, dict):
                        cells = row.get("cells")
                        if isinstance(cells, list) and cells:
                            for cell in cells:
                                cell_kids = cell.get("kids") if isinstance(cell, dict) else None
                                if isinstance(cell_kids, list) and cell_kids:
                                    yield from self._iter_layout_items(cell_kids)
                                elif isinstance(cell, dict) and cell.get("content"):
                                    yield cell
                        continue
            list_items = elem.get("items") or elem.get("list items")
            if isinstance(list_items, list) and list_items:
                yield from self._iter_layout_items(list_items)
                continue
            yield elem

    def _join_text_runs(self, left: str, right: str) -> str:
        if not left:
            return right
        if not right:
            return left
        if left.endswith("-"):
            return f"{left[:-1]}{right.lstrip()}"
        return f"{left.rstrip()} {right.lstrip()}"

    def _merge_bboxes(self, left: Optional[List[float]], right: Optional[List[float]]) -> Optional[List[float]]:
        if not left:
            return right
        if not right:
            return left
        return [
            min(left[0], right[0]),
            min(left[1], right[1]),
            max(left[2], right[2]),
            max(left[3], right[3]),
        ]

    def _is_header_footer_run(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return True
        header_footer_patterns = [
            r"^\d+$",
            r"(?i)^page\s+\d+$",
            r"(?i)^doi:",
            r"(?i)^https?://",
            r"(?i)^contents lists available",
        ]
        return any(re.match(pattern, normalized) for pattern in header_footer_patterns)

    def _can_merge_text_runs(self, previous: BlockInfo, current: BlockInfo) -> bool:
        if previous.kind != "paragraph" or current.kind != "paragraph":
            return False
        if previous.page != current.page or previous.section != current.section:
            return False
        if previous.bbox is None or current.bbox is None:
            return False
        if self._is_header_footer_run(previous.text) or self._is_header_footer_run(current.text):
            return False

        prev_bbox = previous.bbox
        curr_bbox = current.bbox
        prev_left = prev_bbox[0]
        curr_left = curr_bbox[0]
        prev_width = max(prev_bbox[2] - prev_bbox[0], 1.0)
        curr_width = max(curr_bbox[2] - curr_bbox[0], 1.0)
        x_tolerance = max(18.0, min(prev_width, curr_width) * 0.08)
        if abs(prev_left - curr_left) > x_tolerance:
            return False

        vertical_gap = prev_bbox[1] - curr_bbox[3]
        if vertical_gap < -6 or vertical_gap > 28:
            return False

        return True

    def _merge_text_runs(self, blocks: List[BlockInfo]) -> List[BlockInfo]:
        raw_paragraph_count = sum(1 for block in blocks if block.kind == "paragraph")
        if not blocks:
            logger.info("merged paragraph runs: raw=0 merged=0")
            return []

        merged_blocks: List[BlockInfo] = []
        for block in blocks:
            if merged_blocks and self._can_merge_text_runs(merged_blocks[-1], block):
                previous = merged_blocks[-1]
                previous.text = self._join_text_runs(previous.text, block.text)
                previous.kid_ids.extend(block.kid_ids)
                previous.bbox = self._merge_bboxes(previous.bbox, block.bbox)
                continue

            merged_blocks.append(
                BlockInfo(
                    block_id=block.block_id,
                    page=block.page,
                    section=block.section,
                    kind=block.kind,
                    kid_ids=list(block.kid_ids),
                    bbox=list(block.bbox) if block.bbox else None,
                    text=block.text,
                )
            )

        for index, block in enumerate(merged_blocks, start=1):
            block.block_id = f"B{index:04d}"

        merged_paragraph_count = sum(1 for block in merged_blocks if block.kind == "paragraph")
        logger.info("merged paragraph runs: raw=%s merged=%s", raw_paragraph_count, merged_paragraph_count)
        return merged_blocks

    # ---------- SI 目录页过滤 ----------
    def _is_toc_heading(self, text: str) -> bool:
        """判断是否为 SI 目录页标题行"""
        normalized = self._normalize_heading_token_spaces(text).strip()
        return bool(re.match(
            r'(?i)^(?:table\s+of\s+contents?|contents?)\s*$',
            normalized
        ))

    def _is_supplementary_toc_entry(self, text: str) -> bool:
        """判断是否为 SI 目录条目（Supplementary Figure X. / Supplementary Table X.）"""
        normalized = self._normalize_text(text)
        return bool(re.match(
            r'(?i)^supplementary\s+(?:figure|fig\.?|table|scheme|note|text|section)\s*S?\d*',
            normalized
        ))

    def _detect_supplementary_toc_pages(self) -> Set[int]:
        if self.document_kind != "supplementary":
            return set()

        page_stats = defaultdict(lambda: {"heading": 0, "entry": 0, "fragment": 0})
        for elem in self._iter_layout_items():
            elem_type = elem.get("type")
            if elem_type in ("image", "picture"):
                continue
            page = elem.get("page number", 1)
            content = self._normalize_text(elem.get("content", ""))
            if not content:
                continue
            if elem_type == "heading" and self._is_toc_heading(content):
                page_stats[page]["heading"] += 1
            if self._is_supplementary_toc_entry(content):
                page_stats[page]["entry"] += 1
            elif self._looks_like_supplementary_toc_text(content):
                page_stats[page]["fragment"] += 1

        toc_pages = {
            page for page, stats in page_stats.items()
            if stats["heading"] or stats["entry"] >= 4 or (stats["entry"] >= 2 and stats["fragment"] >= 2)
        }
        expanded_pages = set(toc_pages)
        for page, stats in page_stats.items():
            if page in toc_pages:
                continue
            if stats["entry"] >= 2 and ((page - 1) in toc_pages or (page + 1) in toc_pages):
                expanded_pages.add(page)
        return expanded_pages

    def _detect_atlas_toc_pages(self) -> Set[int]:
        if not self.is_atlas or self.document_kind != "supplementary":
            return set()

        atlas_cfg = self.config.get("supplementary_atlas", {})
        page_limit = atlas_cfg.get("toc_detection_page_range", 3)
        entry_threshold = atlas_cfg.get("toc_entry_threshold", 4)
        page_stats = defaultdict(lambda: {"entries": 0, "heading": 0, "narrative": 0})

        for elem in self._iter_layout_items():
            page = elem.get("page number", 1)
            if page > max(3, page_limit):
                continue
            if elem.get("type") in ("image", "picture"):
                continue
            text = self._normalize_text(elem.get("content", ""))
            if not text:
                continue
            if self._is_toc_heading(text):
                page_stats[page]["heading"] += 1
                continue
            if self._is_supplementary_toc_entry(text):
                page_stats[page]["entries"] += 1
                continue
            sentences = self._split_sentences(text)
            if len(sentences) >= 2 or len(text) > 220:
                page_stats[page]["narrative"] += 1

        toc_pages = set()
        for page, stats in page_stats.items():
            if stats["heading"] > 0:
                toc_pages.add(page)
                continue
            if stats["entries"] >= entry_threshold and stats["narrative"] <= 1:
                toc_pages.add(page)
                continue
            if stats["entries"] >= max(2, entry_threshold - 1) and page in {2, 3} and stats["narrative"] == 0:
                toc_pages.add(page)

        expanded = set(toc_pages)
        for page, stats in page_stats.items():
            if page in toc_pages:
                continue
            if stats["entries"] >= 2 and stats["narrative"] == 0 and ((page - 1) in toc_pages or (page + 1) in toc_pages):
                expanded.add(page)
        return expanded

    def _normalize_kids(self) -> List[BlockInfo]:
        raw_blocks: List[BlockInfo] = []
        current_section = "introduction"
        block_index = 1
        abstract_active = False
        abstract_start_page: Optional[int] = None
        suppressed_section: Optional[str] = None
        self.document_kind = self._detect_document_kind()
        logger.info("document_kind=%s", self.document_kind)
        
        # 检测是否为图册型 SI 文献
        self.is_atlas = self._detect_supplementary_atlas()
        if self.is_atlas:
            logger.info("Document type: supplementary_atlas mode enabled")
        
        toc_pages = self._detect_supplementary_toc_pages()
        if toc_pages:
            logger.info("supplementary TOC pages detected: %s", sorted(toc_pages))
        
        # =============================================================
        # Atlas 专用：页级 TOC 压制
        # 对于 atlas 类型文档，如果某页被判定为 TOC 页，整页压制
        # =============================================================
        if self.is_atlas and self.document_kind == "supplementary":
            atlas_toc_pages = self._detect_atlas_toc_pages()
            if atlas_toc_pages:
                logger.info("ATLAS TOC pages (page-level suppression): %s", sorted(atlas_toc_pages))
            # 合并普通 TOC 页和 atlas TOC 页
            toc_pages = toc_pages.union(atlas_toc_pages)

        # ── SI TOC 过滤状态 ──────────────────────────────────────────────────
        # 当检测到 SI TOC 标题后，进入 toc_suppression 模式；
        # 连续遇到 supplementary 条目则丢弃；遇到非条目内容则退出。
        in_toc_suppression = False
        toc_suppression_count = 0  # 连续条目数，<2 则不确认是 TOC，回退

        def switch_section(next_section: str, reason: str):
            nonlocal current_section
            if current_section != next_section:
                logger.info("section switch %s -> %s (%s)", current_section, next_section, reason)
                current_section = next_section

        for kid_index, elem in enumerate(self._iter_layout_items(), start=1):
            elem_type = elem.get("type")
            if elem_type in ("image", "picture"):
                continue

            page = elem.get("page number", 1)
            bbox = elem.get("bounding box") if elem.get("bounding box") else None

            candidate_texts: List[str] = []
            if elem_type == "list":
                items = elem.get("list items", [])
                candidate_texts = [
                    self._normalize_text(item.get("content", "") if isinstance(item, dict) else str(item))
                    for item in items
                ]
            else:
                candidate_texts = [self._normalize_text(elem.get("content", ""))]

            for text in candidate_texts:
                if not text:
                    continue
                if elem_type != "heading" and self._is_noise(text):
                    continue

                # ── SI TOC 过滤逻辑 ──────────────────────────────────────
                if self.document_kind == "supplementary":
                    if page in toc_pages:
                        continue
                    if elem_type == "heading" and self._is_toc_heading(text):
                        in_toc_suppression = True
                        toc_suppression_count = 0
                        logger.info("SI TOC heading detected: %r — entering toc_suppression", text)
                        continue  # 目录标题本身也丢弃

                    if in_toc_suppression:
                        if self._is_supplementary_toc_entry(text):
                            toc_suppression_count += 1
                            logger.debug("SI TOC entry suppressed (%d): %r", toc_suppression_count, text[:80])
                            continue  # 丢弃 TOC 条目
                        else:
                            # 退出 TOC 压制
                            if toc_suppression_count > 0:
                                logger.info(
                                    "SI TOC suppression ended after %d entries; resuming at: %r",
                                    toc_suppression_count, text[:80]
                                )
                            in_toc_suppression = False
                            toc_suppression_count = 0
                            # 当前 text 不是 TOC 条目，继续正常处理

                kind = self._classify_block_kind(elem, text)
                if elem_type == "heading":
                    detected_kind = self._detect_document_kind(text)
                    if detected_kind == "supplementary" and self.document_kind != "supplementary" and page <= 2:
                        self.document_kind = "supplementary"
                        logger.info("document_kind=%s", self.document_kind)
                    suppressed_section = None
                    detected = self._detect_heading_section(text)
                    if detected == "metadata":
                        logger.info("section switch %s -> metadata (%s)", current_section, text)
                        abstract_active = False
                        suppressed_section = "metadata"
                        switch_section("metadata", text)
                    elif detected == "backmatter":
                        logger.info("section switch %s -> backmatter (%s)", current_section, text)
                        abstract_active = False
                        if detected_kind != "supplementary":
                            suppressed_section = "backmatter"
                        switch_section("backmatter", text)
                    elif detected != "unknown":
                        switch_section(detected, text)
                        abstract_active = detected == "abstract"
                        abstract_start_page = page if abstract_active else None
                elif suppressed_section:
                    if self._is_abstract_start(text):
                        switch_section("abstract", text)
                        abstract_active = True
                        abstract_start_page = page
                        suppressed_section = None
                    else:
                        continue
                elif self._is_abstract_start(text):
                    switch_section("abstract", text)
                    abstract_active = True
                    abstract_start_page = page
                elif abstract_active and abstract_start_page is not None and page > abstract_start_page:
                    switch_section("introduction", f"page break after abstract p{abstract_start_page}")
                    abstract_active = False

                block_section = "metadata" if kind == "metadata" else current_section
                raw_blocks.append(
                    BlockInfo(
                        block_id=f"B{block_index:04d}",
                        page=page,
                        section=block_section,
                        kind=kind,
                        kid_ids=[kid_index],
                        bbox=bbox,
                        text=text,
                    )
                )
                block_index += 1

        return self._merge_text_runs(raw_blocks)

    def _detect_assay_type(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        if "uv-vis" in text_lower:
            return "uv_vis_kinetics" if any(token in text_lower for token in ["km", "vmax", "kinetic"]) else "uv_vis_activity"
        if "sers" in text_lower:
            return "sers_kinetics" if any(token in text_lower for token in ["km", "vmax", "kinetic"]) else "sers_activity"
        if "lineweaver-burk" in text_lower or "kinetic" in text_lower:
            return "other"
        return None

    def _merge_unique(self, left: List[Any], right: List[Any]) -> List[Any]:
        merged: List[Any] = []
        for item in list(left) + list(right):
            if item in (None, "", []):
                continue
            if item not in merged:
                merged.append(item)
        return merged

    def _extract_sentences_from_blocks(self, blocks: List[BlockInfo]) -> List[SentenceInfo]:
        sentences: List[SentenceInfo] = []

        for block in blocks:
            raw_sentences = (
                [block.text]
                if block.kind in ("heading", "metadata")
                else self._split_sentences(block.text)
            )
            if not raw_sentences:
                raw_sentences = [block.text]
            for sent in raw_sentences:
                sent = sent.strip()
                if len(sent) < self.config["min_sentence_length"] and block.kind not in ("caption", "heading", "metadata"):
                    continue
                sent = self._normalize_scientific_notation(sent)
                source_kind = "caption" if block.kind == "caption" else "text"
                if self._looks_like_figure_ocr(sent):
                    source_kind = "figure_ocr"
                score = self._calculate_sentence_score(sent, block.section)
                contains_keyword = bool(self._keyword_pattern.search(sent.lower())) if self._keyword_pattern else False
                sentences.append(
                    SentenceInfo(
                        sentence_id="",
                        text=sent,
                        section=block.section,
                        page=block.page,
                        score=score,
                        contains_numeric=bool(re.search(r"\d", sent)),
                        contains_keyword=contains_keyword,
                        kid_ids=block.kid_ids,
                        bbox=block.bbox,
                        source_kind=source_kind,
                        block_id=block.block_id,
                    )
                )

        return sentences

    def _select_high_value_sentences(self, sentences: List[SentenceInfo]) -> List[SentenceInfo]:
        if not sentences:
            logger.info("text gate dropped: {}")
            self.diagnostics["dropped_text_reasons"] = {}
            return []

        for sentence in sentences:
            # raw_text：保留原始句子（仅做基础空白合并）
            raw_t = self._normalize_text_basic(sentence.text)
            # normalized_text：给 LLM 看的保守清洗版本
            sentence.normalized_text = self._normalize_scientific_text_v2(sentence.text)
            # search_text 临时存入 value_tags（不破坏现有 SentenceInfo 字段）
            # 评分/关键词匹配使用 _normalize_for_search 结果
            sentence._search_text = self._normalize_for_search(sentence.text)
            sentence._raw_text = raw_t
            self._tag_sentence(sentence)
            self._hard_recall_guardrail(sentence)
            self._annotate_sentence_signals(sentence)

        dropped_counts = defaultdict(int)
        kept: List[SentenceInfo] = []
        hard_recall_drop_rescues = 0
        for sentence in sentences:
            drop_reason = self._drop_before_scoring(sentence)
            if drop_reason and not sentence.hard_recall:
                dropped_counts[drop_reason] += 1
                continue
            if drop_reason and sentence.hard_recall:
                dropped_counts[f"{drop_reason}_hard_recall_rescued"] += 1
                hard_recall_drop_rescues += 1
            kept.append(sentence)

        kept, context_expanded_count = self._expand_hard_recall_context(sentences, kept)

        hard_recall_count = sum(1 for s in kept if s.hard_recall)
        hard_recall_ids = [s.sentence_id for s in kept if s.hard_recall]
        hard_recall_block_ids = sorted({s.block_id for s in kept if s.hard_recall and s.block_id})
        hard_recall_kid_ids = sorted({
            kid_id
            for s in kept
            if s.hard_recall
            for kid_id in (s.kid_ids or [])
        })
        hard_recall_patterns_hit = defaultdict(int)
        for s in kept:
            if s.hard_recall:
                for p in s.hard_recall_patterns:
                    hard_recall_patterns_hit[p] += 1
        context_marked_count = sum(
            1 for s in kept if "context_expansion" in (s.hard_recall_patterns or [])
        )
        logger.info("text gate dropped: %s", dict(sorted(dropped_counts.items())))
        logger.info("hard recall: %d sentences, patterns: %s", hard_recall_count, dict(sorted(hard_recall_patterns_hit.items())))
        self.diagnostics["dropped_text_reasons"] = dict(sorted(dropped_counts.items()))
        self.diagnostics["hard_recall_count"] = hard_recall_count
        self.diagnostics["hard_recall_sentence_ids"] = hard_recall_ids
        self.diagnostics["hard_recall_block_ids"] = hard_recall_block_ids
        self.diagnostics["hard_recall_kid_ids"] = hard_recall_kid_ids
        self.diagnostics["hard_recall_patterns_hit"] = dict(sorted(hard_recall_patterns_hit.items()))
        self.diagnostics["hard_recall_context_expanded_count"] = (
            context_expanded_count + hard_recall_drop_rescues + context_marked_count
        )
        return kept

    def _primary_role(self, sentence: SentenceInfo) -> str:
        role_priority = [
            "application",
            "comparison",
            "mechanism",
            "structure",
            "activity",
            "system",
            "kinetics",
            "assay",
            "paper",
            "supplementary",
        ]
        for role in role_priority:
            if role in sentence.value_tags:
                return role
        return "background" if "background" in sentence.value_tags else "other"

    def _sentence_priority(self, sentence: SentenceInfo) -> float:
        tag_bonus = {
            "paper": 7.0,
            "system": 7.5,
            "activity": 8.0,
            "assay": 5.0,
            "kinetics": 5.5,
            "structure": 7.0,
            "mechanism": 8.0,
            "comparison": 7.0,
            "application": 7.5,
            "supplementary": 3.5,
            "background": -7.0,
        }
        priority = sentence.score
        for tag in sentence.value_tags:
            priority += tag_bonus.get(tag, 0.0)

        high_value_role_count = sum(1 for tag in sentence.value_tags if tag in self._selection_roles())
        if high_value_role_count > 1:
            priority += 0.8 * (high_value_role_count - 1)
        if sentence.contains_numeric and any(tag in sentence.value_tags for tag in ("kinetics", "comparison", "application", "activity", "assay")):
            priority += 1.2
        if sentence.contains_kinetics_signal and 'kinetics' not in sentence.value_tags:
            priority += 1.5
        if sentence.contains_material_signal and 'system' not in sentence.value_tags:
            priority += 0.5
        if sentence.candidate_enzyme_mentions and 'activity' not in sentence.value_tags:
            priority += 0.8
        if sentence.candidate_application_mentions and 'application' not in sentence.value_tags:
            priority += 0.8
        if re.search(
            r"(?i)\b(no|without|lacks?)\s+(?:obvious\s+)?(?:peroxidase|oxidase|catalase|catechol oxidase)[- ]like activity\b",
            sentence.text,
        ):
            priority += 2.5

        section_bonus = {
            "results": 2.0,
            "results_like": 2.0,
            "experimental": 1.2,
            "conclusion": 1.0,
            "abstract": 0.2,
            "introduction": -0.8,
            "unknown": 0.2,
        }
        priority += section_bonus.get(sentence.section, 0.0)
        return priority

    def _selection_sort_key(self, sentence: SentenceInfo) -> Tuple[float, float, int, int]:
        kid_seq = sentence.kid_ids[0] if sentence.kid_ids else 10**9
        return (
            self._sentence_priority(sentence),
            sentence.score,
            -sentence.page,
            -kid_seq,
        )

    def _adaptive_budget_targets(
        self,
        sentences: List[SentenceInfo],
        target_sentences: int,
        target_chars: int,
        hard_max_sentences: int,
        hard_max_chars: int,
    ) -> Tuple[int, int]:
        system_mentions: List[str] = []
        activity_types: Set[str] = set()
        application_hits = 0
        for sentence in sentences:
            system_mentions = self._merge_unique(
                system_mentions,
                self._extract_candidate_system_mentions(sentence.text, sentence.value_tags),
            )
            text_lower = sentence.text.lower()
            for _etype, _meta in ENZYME_REGISTRY.items():
                if _meta["keywords"][0] in text_lower:
                    activity_types.add(_meta["keywords"][0])
            if "application" in sentence.value_tags:
                application_hits += 1

        pages = self.paper_metadata.get("pages") if isinstance(self.paper_metadata, dict) else None
        try:
            page_count = int(pages) if pages is not None else None
        except (TypeError, ValueError):
            page_count = None

        adjusted_sentences = target_sentences
        adjusted_chars = target_chars
        if len(system_mentions) >= 2:
            adjusted_sentences += 4
            adjusted_chars += 800
        if len(activity_types) >= 2:
            adjusted_sentences += 4
            adjusted_chars += 800
        if application_hits >= 2:
            adjusted_sentences += 2
            adjusted_chars += 500
        if page_count is not None and page_count <= 6:
            adjusted_sentences = max(adjusted_sentences, 10)
            adjusted_chars = max(adjusted_chars, 2400)

        return min(adjusted_sentences, hard_max_sentences), min(adjusted_chars, hard_max_chars)

    def _build_role_minima(self, sentences: List[SentenceInfo], target_sentences: int) -> Dict[str, int]:
        available = defaultdict(int)
        for sentence in sentences:
            for role in self._selection_roles():
                if role in sentence.value_tags:
                    available[role] += 1

        pages = self.paper_metadata.get("pages") if isinstance(self.paper_metadata, dict) else None
        try:
            page_count = int(pages) if pages is not None else None
        except (TypeError, ValueError):
            page_count = None
        short_doc = (page_count is not None and page_count <= 6) or len(sentences) <= 160

        minima: Dict[str, int] = {}

        def assign(role: str, desired: int) -> None:
            if available[role] > 0 and desired > 0:
                minima[role] = min(available[role], desired)

        core_quota = 2 if short_doc and target_sentences >= 8 else 1
        assign("system", core_quota)
        assign("activity", core_quota)
        if available["comparison"] > 0:
            assign("comparison", 1)
        else:
            assign("paper", 1)
        if available["mechanism"] > 0:
            assign("mechanism", 1)
        else:
            assign("structure", 1)
        if available["application"] > 0:
            assign("application", 1)
        assign("kinetics", 1)
        if target_sentences >= 10:
            assign("assay", 1)
        if self.document_kind == "supplementary":
            assign("supplementary", 1)
        return minima

    def _role_cap(self, role: str, target_sentences: int, available_count: int) -> int:
        if role == "kinetics":
            return min(available_count, max(2, math.ceil(target_sentences * 0.28)))
        if role == "assay":
            return min(available_count, max(3, math.ceil(target_sentences * 0.40)))
        return available_count

    def _fill_selection_score(
        self,
        sentence: SentenceInfo,
        role_counts: Dict[str, int],
        primary_role_counts: Dict[str, int],
    ) -> float:
        primary_role = self._primary_role(sentence)
        uncovered_bonus = sum(
            1.5 for role in sentence.value_tags
            if role in self._selection_roles() and role_counts.get(role, 0) == 0
        )
        diversity_penalty = primary_role_counts.get(primary_role, 0) * (1.8 if primary_role == "kinetics" else 0.75)
        return self._sentence_priority(sentence) + uncovered_bonus - diversity_penalty

    def _enforce_text_budget(self, sentences: List[SentenceInfo]) -> List[SentenceInfo]:
        if not sentences:
            logger.info("selection budget: target=0 sentences / 0 chars hard=0 sentences / 0 chars")
            logger.info("selected by section: {}")
            self.diagnostics["selection"] = {
                "selected_by_section": {},
                "selected_by_role": {},
                "selected_sentences": 0,
                "selected_chars": 0,
            }
            return []

        budget = self.config.get("text_budget", {})
        target_sentences = budget.get("target_sentences", 42)
        target_chars = budget.get("target_chars", 9000)
        hard_max_sentences = budget.get("hard_max_sentences", 55)
        hard_max_chars = budget.get("hard_max_chars", 12000)
        section_caps = budget.get("section_caps", {})
        if self.document_kind == "supplementary":
            supplementary_caps = {
                "introduction": 15,
                "unknown": 12,
                "experimental": 18,
                "results": 28,
                "results_like": 20,
                "conclusion": 5,
                "abstract": 3,
            }
            for sec, cap in supplementary_caps.items():
                section_caps[sec] = max(section_caps.get(sec, 0), cap)
            target_sentences = max(target_sentences, 50)
            target_chars = max(target_chars, 12000)
            hard_max_sentences = max(hard_max_sentences, 70)
            hard_max_chars = max(hard_max_chars, 16000)
            if self.is_atlas:
                atlas_budget = self.config.get("atlas_budget", {})
                target_sentences = max(target_sentences, atlas_budget.get("target_sentences", 60))
                target_chars = max(target_chars, atlas_budget.get("target_chars", 12000))
                hard_max_sentences = max(hard_max_sentences, atlas_budget.get("hard_max_sentences", 80))
                hard_max_chars = max(hard_max_chars, atlas_budget.get("hard_max_chars", 16000))
        elif self.document_kind == "review":
            review_caps = {
                "introduction": 10,
                "unknown": 15,
                "experimental": 5,
                "results": 20,
                "results_like": 15,
                "conclusion": 5,
                "abstract": 5,
            }
            for sec, cap in review_caps.items():
                section_caps[sec] = max(section_caps.get(sec, 0), cap)
            target_sentences = max(target_sentences, 60)
            target_chars = max(target_chars, 15000)
            hard_max_sentences = max(hard_max_sentences, 80)
            hard_max_chars = max(hard_max_chars, 20000)
        elif self.document_kind == "communication":
            comm_caps = {
                "introduction": 8,
                "unknown": 10,
                "experimental": 10,
                "results": 15,
                "results_like": 10,
                "conclusion": 3,
                "abstract": 3,
            }
            for sec, cap in comm_caps.items():
                section_caps[sec] = max(section_caps.get(sec, 0), cap)
            target_sentences = max(target_sentences, 35)
            target_chars = max(target_chars, 8000)
            hard_max_sentences = max(hard_max_sentences, 50)
            hard_max_chars = max(hard_max_chars, 12000)
        min_priority_floor = self.config.get("min_priority_floor", -4.0)
        target_sentences, target_chars = self._adaptive_budget_targets(
            sentences,
            target_sentences,
            target_chars,
            hard_max_sentences,
            hard_max_chars,
        )

        logger.info(
            "selection budget: target=%s sentences / %s chars hard=%s sentences / %s chars",
            target_sentences,
            target_chars,
            hard_max_sentences,
            hard_max_chars,
        )

        by_section = defaultdict(list)
        by_role = defaultdict(list)
        available_primary_counts = defaultdict(int)
        for sentence in sentences:
            by_section[sentence.section].append(sentence)
            available_primary_counts[self._primary_role(sentence)] += 1
            for role in self._selection_roles():
                if role in sentence.value_tags:
                    by_role[role].append(sentence)

        for section_sentences in by_section.values():
            section_sentences.sort(key=self._selection_sort_key, reverse=True)
        for role_sentences in by_role.values():
            role_sentences.sort(key=self._selection_sort_key, reverse=True)

        selected: List[SentenceInfo] = []
        selected_ids = set()
        selected_chars = 0
        section_counts = defaultdict(int)
        role_counts = defaultdict(int)
        primary_role_counts = defaultdict(int)

        def sentence_chars(sentence: SentenceInfo) -> int:
            return len(self._format_sentence_line(sentence)) + 1

        def can_add(sentence: SentenceInfo, max_sentences: int, max_chars: int) -> bool:
            if self._sentence_priority(sentence) < min_priority_floor:
                return False
            section = sentence.section or "unknown"
            if section_counts[section] >= section_caps.get(section, hard_max_sentences):
                return False
            projected_sentences = len(selected) + 1
            projected_chars = selected_chars + sentence_chars(sentence)
            primary_role = self._primary_role(sentence)
            role_cap = self._role_cap(primary_role, max_sentences, available_primary_counts.get(primary_role, 0))
            if primary_role in self._selection_roles() and primary_role_counts[primary_role] >= role_cap:
                undercovered_roles = [
                    role for role in sentence.value_tags
                    if role in self._selection_roles() and role_counts.get(role, 0) == 0
                ]
                if not undercovered_roles:
                    return False
            return projected_sentences <= max_sentences and projected_chars <= max_chars

        def add_sentence(sentence: SentenceInfo) -> None:
            nonlocal selected_chars
            selected.append(sentence)
            selected_ids.add(id(sentence))
            selected_chars += sentence_chars(sentence)
            section_counts[sentence.section or "unknown"] += 1
            primary_role = self._primary_role(sentence)
            primary_role_counts[primary_role] += 1
            for role in sentence.value_tags:
                if role in self._selection_roles():
                    role_counts[role] += 1

        role_minima = self._build_role_minima(sentences, target_sentences)
        role_order = ["system", "activity", "comparison", "paper", "mechanism", "structure", "application", "kinetics", "assay", "supplementary"]

        hard_recalled = [s for s in sentences if s.hard_recall]
        for sentence in hard_recalled:
            if id(sentence) not in selected_ids:
                add_sentence(sentence)

        for role in role_order:
            needed = role_minima.get(role, 0)
            if needed <= 0:
                continue
            for sentence in by_role.get(role, []):
                if role_counts.get(role, 0) >= needed:
                    break
                if id(sentence) in selected_ids:
                    continue
                if not can_add(sentence, target_sentences, target_chars):
                    continue
                add_sentence(sentence)

        def fill_remaining(max_sentences: int, max_chars: int) -> None:
            while True:
                candidates = [
                    sentence for sentence in sentences
                    if id(sentence) not in selected_ids and can_add(sentence, max_sentences, max_chars)
                ]
                if not candidates:
                    break
                candidates.sort(
                    key=lambda sentence: (
                        self._fill_selection_score(sentence, role_counts, primary_role_counts),
                        *self._selection_sort_key(sentence),
                    ),
                    reverse=True,
                )
                add_sentence(candidates[0])

        fill_remaining(target_sentences, target_chars)
        if len(selected) < min(target_sentences, hard_max_sentences):
            fill_remaining(hard_max_sentences, hard_max_chars)

        logger.info("selected by section: %s", dict(sorted(section_counts.items())))
        logger.info(
            "selected by role: %s",
            dict(sorted((role, count) for role, count in role_counts.items() if count > 0))
        )
        self.diagnostics["selection"] = {
            "selected_by_section": dict(sorted(section_counts.items())),
            "selected_by_role": dict(sorted((role, count) for role, count in role_counts.items() if count > 0)),
            "selected_sentences": len(selected),
            "selected_chars": sum(len(self._format_sentence_line(sentence)) + 1 for sentence in selected),
        }
        return selected

    def _format_sentence_line(self, sentence: SentenceInfo) -> str:
        section = sentence.section or "unknown"
        return f"[{sentence.sentence_id}|p{sentence.page}|{section}] {sentence.text}"

    def _build_multi_chunks(self, sentences: List[SentenceInfo], max_chars: int = 6000) -> List[List[SentenceInfo]]:
        if not sentences:
            return []

        chunks: List[List[SentenceInfo]] = []
        current_chunk: List[SentenceInfo] = []
        current_mentions: List[str] = []
        current_assay: Optional[str] = None
        current_chars = 0

        for sentence in sentences:
            sentence_text = self._format_sentence_line(sentence)
            sentence_chars = len(sentence_text) + 1
            mentions = self._extract_candidate_system_mentions(sentence.text, sentence.value_tags)
            assay_type = self._detect_assay_type(sentence.text)

            should_split = False
            if current_chunk:
                if current_chars + sentence_chars > max_chars:
                    should_split = True
                elif assay_type and current_assay and assay_type != current_assay:
                    should_split = True
                elif mentions and current_mentions and any(mention not in current_mentions for mention in mentions):
                    should_split = True

            if should_split:
                chunks.append(current_chunk)
                current_chunk = []
                current_mentions = []
                current_assay = None
                current_chars = 0

            current_chunk.append(sentence)
            current_chars += sentence_chars
            current_mentions = self._merge_unique(current_mentions, mentions)
            if assay_type:
                current_assay = assay_type

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _should_use_multi_chunk(self, sentences: List[SentenceInfo], refined_text: str) -> bool:
        cfg = self.config.get("adaptive_chunking", {})
        if not cfg.get("enabled", False):
            return False

        if len(refined_text) <= cfg.get("prefer_single_chunk_below_chars", 8000):
            if len(sentences) <= cfg.get("prefer_single_chunk_below_sentences", 40):
                all_mentions: List[str] = []
                for s in sentences:
                    all_mentions = self._merge_unique(all_mentions, self._extract_candidate_system_mentions(s.text, s.value_tags))
                if len(all_mentions) < cfg.get("multi_chunk_min_system_mentions", 3):
                    assay_types = set()
                    for s in sentences:
                        at = self._detect_assay_type(s.text)
                        if at:
                            assay_types.add(at)
                    if len(assay_types) <= 1 and not cfg.get("multi_chunk_on_multi_assay", True):
                        return False
                    if len(assay_types) <= 1:
                        return False

        return True

    # ---------- 主处理流程 ----------
    def process(self):
        """执行预处理：布局流归一化 -> 句子证据 -> 多 chunk 构建"""
        process_start = time.time() if 'time' in globals() else None
        self.blocks = self._normalize_kids()
        self.paper_metadata = self._extract_document_metadata()

        # Metadata fallback: 如果顶层 title/author 为空，尝试从 page-1 提取
        if not self.paper_metadata.get("title") or self._is_junk_title(self.paper_metadata.get("title")):
            fallback_title = self._extract_title_from_pages()
            if fallback_title:
                logger.info("metadata fallback title: %s", fallback_title[:80])
                self.paper_metadata["title"] = fallback_title
        if not self.paper_metadata.get("author"):
            fallback_author = self._extract_authors_from_pages()
            if fallback_author:
                if self.document_kind == "supplementary" and isinstance(fallback_author, str):
                    if re.search(r'(?i)\b(?:college|university|department|institute|academy|laboratory|school of|faculty of)\b', fallback_author):
                        fallback_author = ""
                if fallback_author:
                    logger.info("metadata fallback author: %s", fallback_author[:80])
                    self.paper_metadata["author"] = fallback_author

        all_sentences = self._extract_sentences_from_blocks(self.blocks)
        main_pool = [sentence for sentence in all_sentences if sentence.source_kind != "figure_ocr"]
        self.figure_ocr_sentences = [sentence for sentence in all_sentences if sentence.source_kind == "figure_ocr"]

        self._ref_section_page = self._detect_ref_section_page(self.blocks)

        gated_sentences = self._select_high_value_sentences(main_pool)
        gated_sentences = self._collect_high_value_sentences(gated_sentences)
        budgeted_sentences = self._enforce_text_budget(gated_sentences)
        self.sentences = self._finalize_selected_sentences(budgeted_sentences)
        self.diagnostics["hard_recall_sentence_ids"] = [
            s.sentence_id for s in self.sentences if s.hard_recall
        ]
        self.diagnostics["hard_recall_block_ids"] = sorted({
            s.block_id for s in self.sentences if s.hard_recall and s.block_id
        })
        self.diagnostics["hard_recall_kid_ids"] = sorted({
            kid_id
            for s in self.sentences
            if s.hard_recall
            for kid_id in (s.kid_ids or [])
        })
        self.diagnostics["hard_recall_overflow"] = sum(
            1 for s in gated_sentences if s.hard_recall and s not in budgeted_sentences
        )

        self.refined_text = "\n".join(self._format_sentence_line(sentence) for sentence in self.sentences)

        if self._should_use_multi_chunk(self.sentences, self.refined_text):
            max_chars = self.config.get("adaptive_chunking", {}).get("max_chars_per_chunk", 6000)
            self.chunk_sentence_groups = self._build_multi_chunks(self.sentences, max_chars=max_chars)
        else:
            self.chunk_sentence_groups = [self.sentences] if self.sentences else []

        self.chunk_contexts = self._build_chunk_contexts(self.chunk_sentence_groups)
        self.chunks = [
            "\n".join(self._format_sentence_line(sentence) for sentence in chunk)
            for chunk in self.chunk_sentence_groups
        ]
        chunk_pages = [sorted({sentence.page for sentence in chunk}) for chunk in self.chunk_sentence_groups]
        section_distribution = defaultdict(int)
        for sentence in self.sentences:
            section_distribution[sentence.section or "unknown"] += 1
        self.diagnostics["chunk_stats"] = {
            "raw_sentence_count": len(all_sentences),
            "gated_sentence_count": len(gated_sentences),
            "selected_sentence_count": len(self.sentences),
            "chunk_count": len(self.chunks),
            "chunk_lengths": [len(chunk) for chunk in self.chunk_sentence_groups],
            "chunk_char_lengths": [len(chunk_text) for chunk_text in self.chunks],
            "chunk_pages": chunk_pages,
            "section_distribution": dict(sorted(section_distribution.items())),
        }

        # 处理图像（保持原有功能）
        self._extract_and_rename_images()

        # P4: 表格入链 - 检测表格并将高价值表格注入 chunks
        detected_tables = self._detect_tables()
        self._table_tasks = self._build_table_tasks(detected_tables)
        is_si = getattr(self, "document_kind", "main") == "supplementary"

        # 新版：构建独立 table_extraction_task
        self._table_extraction_task = self._build_table_extraction_task(
            detected_tables, is_supplementary=is_si
        )
        table_ext_stats = self._table_extraction_task.get("stats", {})
        logger.info(
            "table_extraction_task: detected=%d, selected=%d, types=%s, vlm_fallback=%d",
            table_ext_stats.get("total_detected", 0),
            table_ext_stats.get("total_selected", 0),
            table_ext_stats.get("table_types_count", {}),
            table_ext_stats.get("needs_vlm_fallback_count", 0),
        )

        if self._table_tasks:
            top_tables = [t for t in self._table_tasks if t["priority_score"] >= 5.0][:3]
            base_chunk_count = len(self.chunks)
            for t_idx, table_task in enumerate(top_tables, start=1):
                content_text = self._clean_table_references(table_task['content_text'])
                context_hint = self._build_table_context_hint(content_text)
                table_chunk_text = f"{context_hint}\n[Table] {table_task['caption']}\n{content_text}"
                self.chunks.append(table_chunk_text)
                table_caption = table_task.get('caption', '')
                table_content = table_task.get('content_text', '')
                table_text_combined = f"{table_caption} {table_content}"
                self.chunk_contexts.append({
                    "chunk_index": len(self.chunks) - 1,
                    "chunk_id": f"table_chunk_{t_idx:03d}",
                    "section": "table",
                    "section_type": "table",
                    "is_caption": False,
                    "is_table_related": True,
                    "is_supplementary": self.document_kind == "supplementary",
                    "pages": sorted(set(table_task.get("pages", []))),
                    "sections": ["table"],
                    "candidate_system_mentions": self._extract_candidate_system_mentions(table_text_combined),
                    "candidate_enzyme_mentions": self._extract_candidate_enzyme_mentions(table_text_combined),
                    "candidate_substrate_mentions": self._extract_candidate_substrate_mentions(table_text_combined),
                    "candidate_application_mentions": self._extract_candidate_application_mentions(table_text_combined),
                    "contains_kinetics_signal": self._detect_kinetics_signal(table_text_combined),
                    "contains_numeric_signal": bool(re.search(r'\d', table_text_combined)),
                    "contains_material_signal": self._detect_material_signal(table_text_combined),
                    "signal_types": sorted({"kinetics"} if self._detect_kinetics_signal(table_text_combined) else set()),
                    "figure_labels": [],
                    "sentence_ids": [],
                })
            logger.info("table tasks: %d detected, %d injected into chunks", len(self._table_tasks), len(top_tables))

        if getattr(self, "document_kind", "main") == "supplementary":
            merged = True
            while merged:
                merged = False
                for i in range(len(self.chunks)):
                    if len(self.chunks[i]) < 200 and not self.chunks[i].strip().startswith("[Table]"):
                        if i < len(self.chunks) - 1:
                            self.chunks[i + 1] = self.chunks[i] + "\n" + self.chunks[i + 1]
                            if i < len(self.chunk_contexts) and i + 1 < len(self.chunk_contexts):
                                self.chunk_contexts[i + 1]["pages"] = sorted(
                                    set(self.chunk_contexts[i + 1].get("pages", []) + self.chunk_contexts[i].get("pages", []))
                                )
                        elif i > 0:
                            self.chunks[i - 1] = self.chunks[i - 1] + "\n" + self.chunks[i]
                        else:
                            continue
                        del self.chunks[i]
                        if i < len(self.chunk_contexts):
                            del self.chunk_contexts[i]
                        merged = True
                        break

        # P2: 引用过滤兜底（在已选句子上再做一轮清理）
        # 注意：主过滤已在 _select_high_value_sentences 中完成，
        # 这里不再重复过滤以避免影响已有主文行为

        logger.info(
            f"处理完成: 原始句子 {len(all_sentences)} -> 高价值 {len(self.sentences)} 句, 生成 {len(self.chunks)} 个 chunk"
        )
        logger.info("chunk diagnostics: %s", self.diagnostics["chunk_stats"])
        if process_start is not None:
            logger.info("preprocess total seconds: %.2f", time.time() - process_start)
        return self

    # ---------- 图像处理 ----------
    def _is_page1_decorative(self, page: int, bbox: List[float], width: float, height: float) -> bool:
        if page != 1:
            return False
        geom = self._bbox_geom(bbox) if bbox and len(bbox) >= 4 else None
        if width > 600 and height < 80:
            return True
        if height < 40 and width < 120:
            return True
        aspect = width / max(height, 1)
        if aspect > 15 and height < 60:
            return True
        if geom and (geom["cx"] < 50 or geom["cx"] > 550 or geom["cy"] < 30):
            if width < 180 or height < 70 or aspect > 12:
                return True
        return False

    def _bbox_geom(self, bbox: List[float]) -> Dict[str, float]:
        x0, y0, x1, y1 = bbox
        left = min(x0, x1)
        right = max(x0, x1)
        top = min(y0, y1)
        bottom = max(y0, y1)
        return {
            "left": left,
            "right": right,
            "top": top,
            "bottom": bottom,
            "width": max(0.0, right - left),
            "height": max(0.0, bottom - top),
            "cx": (left + right) / 2.0,
            "cy": (top + bottom) / 2.0,
        }

    def _x_overlap_ratio(self, a: List[float], b: List[float]) -> float:
        geom_a = self._bbox_geom(a)
        geom_b = self._bbox_geom(b)
        intersection = max(0.0, min(geom_a["right"], geom_b["right"]) - max(geom_a["left"], geom_b["left"]))
        denominator = max(1.0, min(geom_a["width"], geom_b["width"]))
        return intersection / denominator

    def _vertical_distance(self, a: List[float], b: List[float]) -> float:
        geom_a = self._bbox_geom(a)
        geom_b = self._bbox_geom(b)
        if geom_a["bottom"] < geom_b["top"]:
            return geom_b["top"] - geom_a["bottom"]
        if geom_b["bottom"] < geom_a["top"]:
            return geom_a["top"] - geom_b["bottom"]
        return 0.0

    def _has_adjacent_figure_reference(self, page: int, bbox: List[float], caption_map: Dict) -> bool:
        """
        判断同页是否存在 Figure/Fig 引用但 caption 配对失败。
        bbox 语义: [left, y_top, right, y_bottom]，y_top < y_bottom。
        规则: 同页 caption + caption_bottom <= image_top + 垂直间距 < 200px。
        无 bbox 时不做宽松 fallback（返回 False）。
        """
        if not bbox or len(bbox) < 4:
            return False
        img_geom = self._bbox_geom(bbox)
        for cid, info in caption_map.items():
            if info.get('page') != page:
                continue
            cap_bbox = info.get('bbox', [])
            if not cap_bbox or len(cap_bbox) < 4:
                continue
            cap_geom = self._bbox_geom(cap_bbox)
            gap = img_geom["top"] - cap_geom["bottom"]
            if 0 <= gap < 200 and self._x_overlap_ratio(bbox, cap_bbox) >= 0.25:
                return True
        return False

    def _bbox_uid_fragment(self, bbox: Optional[List[float]]) -> str:
        if not bbox or len(bbox) < 4:
            return "no_bbox"
        return "_".join(str(int(round(value))) for value in bbox[:4])

    def _build_image_uid(self, elem: Dict[str, Any], ordinal: int) -> Tuple[str, str]:
        raw_id = elem.get("id")
        if raw_id not in (None, ""):
            return f"id::{raw_id}", "id"
        source = elem.get("source")
        if source:
            page = elem.get("page number", 1)
            bbox_key = self._bbox_uid_fragment(elem.get("bounding box"))
            return f"source::{source}::p{page}::{bbox_key}::{ordinal}", "source"
        page = elem.get("page number", 1)
        bbox_key = self._bbox_uid_fragment(elem.get("bounding box"))
        return f"surrogate::p{page}::{bbox_key}::{ordinal}", "surrogate"

    def _build_caption_uid(self, elem: Dict[str, Any], figure_id: str, ordinal: int) -> str:
        raw_id = elem.get("id")
        if raw_id not in (None, ""):
            return f"caption-id::{raw_id}"
        page = elem.get("page number", 1)
        bbox_key = self._bbox_uid_fragment(elem.get("bounding box"))
        return f"caption::{figure_id}::p{page}::{bbox_key}::{ordinal}"

    def _normalize_image_elements(self) -> List[Dict[str, Any]]:
        normalized = []
        self.image_key_source_stats = defaultdict(int)
        for ordinal, elem in enumerate(self._iter_layout_items(), start=1):
            if elem.get("type") not in ("image", "picture"):
                continue
            source = elem.get("source", "")
            if not source:
                continue
            candidates = [self.images_root / source, self.json_path.parent / source]
            original_path = next((str(path) for path in candidates if path.exists()), str(candidates[0]))
            bbox = elem.get("bounding box", [])
            image_uid, uid_source = self._build_image_uid(elem, ordinal)
            self.image_key_source_stats[uid_source] += 1
            normalized.append(
                {
                    "image_uid": image_uid,
                    "uid_source": uid_source,
                    "page": elem.get("page number", 1),
                    "bbox": bbox,
                    "source": source,
                    "elem_type": elem.get("type", "image"),
                    "raw_elem": elem,
                    "original_path": original_path,
                    "description": elem.get("description", "") or "",
                    "width": bbox[2] - bbox[0] if len(bbox) >= 4 else 0,
                    "height": bbox[3] - bbox[1] if len(bbox) >= 4 else 0,
                    "ordinal": ordinal,
                }
            )
        self.normalized_images = normalized
        self.diagnostics["image_key_sources"] = dict(sorted(self.image_key_source_stats.items()))
        logger.info("normalized images: total=%s key_sources=%s", len(normalized), self.diagnostics["image_key_sources"])
        return normalized

    def _normalize_caption_elements(self) -> List[Dict[str, Any]]:
        normalized = []
        for ordinal, elem in enumerate(self._iter_layout_items(), start=1):
            content = self._normalize_text(elem.get("content", ""))
            bbox = elem.get("bounding box", [])
            if not content or not bbox or len(bbox) < 4:
                continue
            parsed = self._parse_caption_label(content)
            if not parsed:
                continue
            figure_kind, figure_number = parsed
            figure_id = f"{figure_kind}_{figure_number:03d}"
            normalized.append(
                {
                    "caption_uid": self._build_caption_uid(elem, figure_id, ordinal),
                    "page": elem.get("page number", 1),
                    "bbox": bbox,
                    "text": content,
                    "figure_kind": figure_kind,
                    "figure_number": figure_number,
                    "figure_id": figure_id,
                    "raw_elem": elem,
                    "ordinal": ordinal,
                }
            )
        self.normalized_captions = normalized
        logger.info("normalized captions: total=%s", len(normalized))
        return normalized

    def _extract_and_rename_images(self):
        """
        从解析 JSON 的 kids 中提取图像，
        根据图注（caption）重命名图像文件，
        输出到 self.images 列表（供 to_mid_json 生成 vlm_tasks）。

        图像过滤策略：
        1. 根据 bbox 尺寸过滤（过小的图像可能是图标/logo）
        2. 无 caption 的图像要求尺寸更大
        3. 文件大小过滤
        """

        # 获取图像过滤配置
        img_filter = self.config.get('image_filter', {})
        min_file_size_kb = img_filter.get('min_file_size_kb', 10)
        min_dimension = img_filter.get('min_dimension', 50)
        min_dimension_with_caption = img_filter.get('min_dimension_with_caption', 30)
        uncaptioned_min_both = img_filter.get('uncaptioned_min_both', 200)
        require_caption_for_small = img_filter.get('require_caption_for_small', True)
        allow_uncaptioned_in_supplementary = img_filter.get('allow_uncaptioned_in_supplementary', False)
        max_images = img_filter.get(
            'max_images_supplementary' if self.document_kind == "supplementary" else 'max_images_main',
            6 if self.document_kind == "supplementary" else 8,
        )

        image_elems = self._normalize_image_elements()

        if not image_elems:
            logger.info("未找到图像元素，跳过图像处理")
            self.images = []
            self.figures = []
            return

        logger.info(f"找到 {len(image_elems)} 个图像元素")
        self.images = []
        self.figures = []

        # 2. 收集所有 caption 文本
        caption_map = self._find_captions()

        # 3. 处理每个图像
        high_value_dir = self.high_value_dir
        high_value_dir.mkdir(parents=True, exist_ok=True)

        filtered_count = 0
        filtered_reasons = defaultdict(int)
        used_output_names: Dict[str, str] = {}
        duplicate_outputs: List[Dict[str, str]] = []

        for image_index, img in enumerate(image_elems, start=1):
            img_id = img['image_uid']
            page = img['page']
            bbox = img['bbox']
            original_path = img['original_path']
            width = img['width']
            height = img['height']

            # ---------- 图像有效性过滤 ----------
            caption_info = caption_map.get(img_id, {})
            caption = caption_info.get("text", "")
            has_caption = bool(caption)

            # 检查1: 文件存在性（必须）
            if not os.path.exists(original_path):
                filtered_count += 1
                filtered_reasons["文件不存在"] += 1
                logger.debug(f"跳过图像: {img['source']} - 文件不存在")
                continue

            # 检查2: 尺寸要求（caption 影响阈值）
            effective_min = min_dimension_with_caption if has_caption else min_dimension
            if width < effective_min and height < effective_min:
                filtered_count += 1
                filtered_reasons[f"尺寸过小({width:.0f}x{height:.0f})"] += 1
                logger.debug(f"跳过图像: {img['source']} - 尺寸过小")
                continue

            # 检查3: 无 caption 小图强制过滤
            if require_caption_for_small and not has_caption:
                if width < uncaptioned_min_both or height < uncaptioned_min_both:
                    filtered_count += 1
                    filtered_reasons[f"无caption小图({width:.0f}x{height:.0f})"] += 1
                    logger.debug(f"跳过图像: {img['source']} - require_caption_for_small")
                    continue

            # 检查4: 文件大小要求
            file_size_kb = os.path.getsize(original_path) / 1024
            if file_size_kb < min_file_size_kb:
                filtered_count += 1
                filtered_reasons[f"文件过小({file_size_kb:.1f}KB)"] += 1
                logger.debug(f"跳过图像: {img['source']} - 文件过小")
                continue

            # ---------- 分级置信过滤 ----------
            # 高置信：有 caption → 直接进入 vlm_tasks
            # 中置信：无 caption，但满足正文图特征 → 也允许进入
            # 低置信：无 caption，且不满足正文图特征 → 丢弃
            vlm_reason = None
            if caption:
                vlm_reason = "caption"
            elif self._is_page1_decorative(page, bbox, width, height):
                filtered_count += 1
                filtered_reasons[f"首页装饰图({width:.0f}x{height:.0f})"] += 1
                logger.debug(f"跳过图像: {img['source']} - 首页装饰图")
                continue
            elif self.document_kind == "supplementary" and not allow_uncaptioned_in_supplementary:
                filtered_count += 1
                filtered_reasons["supplementary_no_uncaptioned"] += 1
                continue
            elif width >= uncaptioned_min_both and height >= uncaptioned_min_both:
                vlm_reason = f"large_uncaptioned({width:.0f}x{height:.0f})"
            elif self._has_adjacent_figure_reference(page, bbox, caption_map):
                vlm_reason = "failed_caption_match"
            else:
                filtered_count += 1
                filtered_reasons[f"低置信无caption({width:.0f}x{height:.0f})"] += 1
                logger.debug(f"跳过图像: {img['source']} - 低置信无caption")
                continue

            # ---------- 处理有效图像 ----------
            # 保留原始文件名，不做重命名
            figure_id = caption_info.get("figure_id") or self._infer_figure_id(caption, image_index)

            if not caption:
                fallback = self._find_fallback_caption(figure_id, page)
                if fallback:
                    caption = f"[auto-detected] {fallback}"
                else:
                    caption = f"Figure from {os.path.basename(original_path)}"
            source_basename = os.path.basename(original_path)
            source_suffix = Path(source_basename).suffix
            new_path = high_value_dir / source_basename
            if source_basename in used_output_names and used_output_names[source_basename] != img_id:
                safe_token = re.sub(r"[^A-Za-z0-9_.-]+", "_", figure_id or img_id)[:80]
                dedup_name = f"{Path(source_basename).stem}__{safe_token}{source_suffix}"
                duplicate_outputs.append({
                    "name": source_basename,
                    "resolved_name": dedup_name,
                    "image_uid": img_id,
                })
                logger.warning("duplicate output filename detected: %s -> %s", source_basename, dedup_name)
                new_path = high_value_dir / dedup_name
                source_basename = dedup_name
            used_output_names[source_basename] = img_id

            # 复制文件
            image_path = None
            try:
                shutil.copy2(original_path, new_path)
                if Path(new_path).exists():
                    image_path = str(Path(new_path).resolve())
                    self.renamed_count += 1
                    logger.info("copy verify ok: %s", image_path)
                else:
                    logger.info("copy verify failed: target missing for %s", original_path)
            except Exception as e:
                logger.warning(f"复制图像失败 {original_path}: {e}")

            # 记录到 self.images（用绝对路径，确保 VLM 能找到）
            self.images.append({
                'original_path': str(Path(original_path).resolve()),
                'image_path': image_path,
                'caption': caption,
                'page': page,
                'figure_id': figure_id,
                'image_uid': img_id,
                'has_caption': bool(caption),
                'vlm_reason': vlm_reason,
                'description': img.get('description', ''),
                'elem_type': img.get('elem_type', 'image'),
            })
            self.figures.append(
                FigureInfo(
                    figure_id=figure_id,
                    page=page,
                    image_kid_id=img_id,
                    bbox=bbox if bbox else None,
                    image_path=image_path or str(Path(original_path).resolve()),
                    caption_kid_ids=[],
                    caption_text=caption,
                )
            )

        # 日志输出过滤统计
        if filtered_count > 0:
            reason_str = ", ".join([f"{k}({v})" for k, v in filtered_reasons.items()])
            logger.info(f"图像过滤: 跳过 {filtered_count}/{len(image_elems)} 个 ({reason_str})")
        self.diagnostics["dropped_image_reasons"] = dict(sorted(filtered_reasons.items()))
        self.diagnostics["duplicate_output_filenames"] = duplicate_outputs

        self.images.sort(key=lambda img: self._image_priority(img))
        # 应用 P6 排序
        is_si = self.document_kind == "supplementary"
        if self.images:
            ranked = self._rank_images(self.images, is_supplementary=is_si)
            ranked = self._drop_large_uncaptioned_on_captioned_pages(ranked)
            ranked = self._drop_uncaptioned_figure_id_collisions(ranked)
            self.images = ranked
        if len(self.images) > max_images:
            logger.info("vlm cap applied: kept %s/%s for %s", max_images, len(self.images), self.document_kind)
            self.images = self.images[:max_images]
            kept_ids = {img["figure_id"] for img in self.images}
            self.figures = [figure for figure in self.figures if figure.figure_id in kept_ids]

        # 统计有caption和无caption的图像数量
        captioned_count = sum(1 for img in self.images if img.get('has_caption'))
        uncaptioned_count = len(self.images) - captioned_count
        logger.info(f"图像处理完成: {len(self.images)} 个高价值图像 -> {self.high_value_dir}")
        logger.info(f"  - 有图注: {captioned_count} 个")
        logger.info(f"  - 无图注: {uncaptioned_count} 个")

    def _find_captions(self) -> Dict[str, Dict[str, Any]]:
        """
        扫描 kids，找到所有正式 caption 相关文本，返回 {image_id: caption_info} 映射。
        接受任意 elem type（caption / paragraph / heading），但必须满足严格句首匹配：
        - ^Figure 数字+
        - ^Fig 数字+
        - ^Scheme 数字+
        """
        caption_candidates = self._collect_caption_candidates()
        self._caption_match_page_stats = []
        logger.info(
            "caption candidates by page: %s",
            {page: [caption["figure_id"] for caption in captions] for page, captions in caption_candidates.items()},
        )
        images_by_page = defaultdict(list)
        for image in self.normalized_images or self._normalize_image_elements():
            if image.get("bbox"):
                images_by_page[image.get("page", 1)].append(image)

        caption_map: Dict[str, Dict[str, Any]] = {}
        total_images = 0
        matched_images = 0
        for page, captions in caption_candidates.items():
            page_images = images_by_page.get(page, [])
            total_images += len(page_images)
            mapping = self._match_page_captions(page, captions, page_images)
            matched_images += len(mapping)
            for image_id, caption in mapping.items():
                caption_map[image_id] = {
                    "text": caption["text"],
                    "page": page,
                    "bbox": caption["bbox"],
                    "figure_id": caption["figure_id"],
                    "caption_uid": caption["caption_uid"],
                }
        match_rate = round(matched_images / max(total_images, 1), 3) if total_images else 0.0
        aggregate_page_stats = {
            "candidate_pairs": sum(item.get("candidate_pairs", 0) for item in self._caption_match_page_stats),
            "matched_pairs": sum(item.get("matched_pairs", 0) for item in self._caption_match_page_stats),
            "ambiguous_skips": sum(item.get("ambiguous_skips", 0) for item in self._caption_match_page_stats),
            "crossing_rejects": sum(item.get("crossing_rejects", 0) for item in self._caption_match_page_stats),
            "residual_recoveries": sum(item.get("residual_recoveries", 0) for item in self._caption_match_page_stats),
            "unmatched_images": sum(item.get("unmatched_images", 0) for item in self._caption_match_page_stats),
            "unmatched_captions": sum(item.get("unmatched_captions", 0) for item in self._caption_match_page_stats),
            "pages": list(self._caption_match_page_stats),
        }
        self.caption_match_stats = {
            "total_images": total_images,
            "matched_images": matched_images,
            "match_rate": match_rate,
            "total_captions": sum(len(captions) for captions in caption_candidates.values()),
            **aggregate_page_stats,
        }
        self.diagnostics["caption_match"] = dict(self.caption_match_stats)
        logger.info("caption match stats: %s", self.caption_match_stats)
        return caption_map

    def _collect_caption_candidates(self) -> Dict[int, List[Dict[str, Any]]]:
        captions_by_page = defaultdict(list)
        for caption in self._normalize_caption_elements():
            captions_by_page[caption["page"]].append(caption)
        return captions_by_page

    def _match_page_captions(self, page: int, captions: List[Dict[str, Any]], images: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        if not captions or not images:
            return {}

        image_filter = self.config.get("image_filter", {})
        max_gap = image_filter.get("max_caption_image_gap", 120)
        min_x_overlap = image_filter.get("min_x_overlap_ratio", 0.25)
        max_center_dx_ratio = image_filter.get("max_center_dx_ratio", 0.35)
        page_width = max((img["bbox"][2] for img in images if img.get("bbox")), default=600.0)
        images_by_id = {image["image_uid"]: image for image in images}
        captions_sorted = sorted(captions, key=lambda item: (item["bbox"][1], item["bbox"][0]))
        candidate_map: Dict[str, List[Dict[str, Any]]] = {}
        image_candidate_scores: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        candidate_pairs = 0
        crossing_rejects = 0
        ambiguous_skips = 0
        residual_recoveries = 0

        for caption in captions_sorted:
            scored_candidates: List[Dict[str, Any]] = []
            caption_geom = self._bbox_geom(caption["bbox"])
            for image in images:
                bbox = image.get("bbox", [])
                if not bbox or len(bbox) < 4:
                    continue
                image_geom = self._bbox_geom(bbox)
                gap_caption_below = caption_geom["top"] - image_geom["bottom"] if caption_geom["top"] >= image_geom["bottom"] else float("inf")
                gap_caption_above = image_geom["top"] - caption_geom["bottom"] if image_geom["top"] >= caption_geom["bottom"] else float("inf")
                directional_gap = min(gap_caption_below, gap_caption_above)
                if directional_gap > max_gap:
                    continue
                x_overlap = self._x_overlap_ratio(caption["bbox"], bbox)
                center_dx = abs(caption_geom["cx"] - image_geom["cx"])
                center_ratio = center_dx / max(page_width, 1.0)
                if x_overlap < min_x_overlap and center_ratio > max_center_dx_ratio:
                    continue
                direction_bonus = 25.0 if gap_caption_below != float("inf") else 14.0
                score = direction_bonus + (30.0 * x_overlap) - (0.14 * directional_gap) - (18.0 * center_ratio)
                scored_candidates.append(
                    {
                        "image_id": image["image_uid"],
                        "score": score,
                    }
                )
                candidate_pairs += 1
                image_candidate_scores[image["image_uid"]].append((caption["caption_uid"], score))
            candidate_map[caption["caption_uid"]] = sorted(scored_candidates, key=lambda item: item["score"], reverse=True)[:4]

        best_score = float("-inf")
        best_pairs: List[Tuple[str, str, float]] = []
        partial_pairs: List[Tuple[str, str, float]] = []

        def _pairs_cross(caption_a: Dict[str, Any], image_a: Dict[str, Any], caption_b: Dict[str, Any], image_b: Dict[str, Any]) -> bool:
            cap_a = self._bbox_geom(caption_a["bbox"])
            cap_b = self._bbox_geom(caption_b["bbox"])
            img_a = self._bbox_geom(image_a["bbox"])
            img_b = self._bbox_geom(image_b["bbox"])
            cap_same_band = abs(cap_a["cy"] - cap_b["cy"]) <= max(cap_a["height"], cap_b["height"]) * 2.0
            img_same_band = abs(img_a["cy"] - img_b["cy"]) <= max(img_a["height"], img_b["height"]) * 0.75
            if cap_same_band and img_same_band:
                if (cap_a["cx"] < cap_b["cx"] and img_a["cx"] > img_b["cx"]) or (cap_a["cx"] > cap_b["cx"] and img_a["cx"] < img_b["cx"]):
                    return True
            cap_same_column = self._x_overlap_ratio(caption_a["bbox"], caption_b["bbox"]) >= 0.4
            img_same_column = self._x_overlap_ratio(image_a["bbox"], image_b["bbox"]) >= 0.4
            if cap_same_column and img_same_column:
                if (cap_a["cy"] < cap_b["cy"] and img_a["cy"] > img_b["cy"]) or (cap_a["cy"] > cap_b["cy"] and img_a["cy"] < img_b["cy"]):
                    return True
            return False

        def _search(idx: int, used_images: Set[str], running_score: float) -> None:
            nonlocal best_score, best_pairs, crossing_rejects
            if idx >= len(captions_sorted):
                if running_score > best_score:
                    best_score = running_score
                    best_pairs = list(partial_pairs)
                return
            caption = captions_sorted[idx]
            _search(idx + 1, used_images, running_score)
            for candidate in candidate_map.get(caption["caption_uid"], []):
                image_id = candidate["image_id"]
                if image_id in used_images:
                    continue
                image = images_by_id.get(image_id)
                if not image:
                    continue
                crossed = False
                for prev_caption_id, prev_image_id, _ in partial_pairs:
                    prev_caption = next((item for item in captions_sorted if item["caption_uid"] == prev_caption_id), None)
                    prev_image = images_by_id.get(prev_image_id)
                    if prev_caption and prev_image and _pairs_cross(caption, image, prev_caption, prev_image):
                        crossed = True
                        crossing_rejects += 1
                        break
                if crossed:
                    continue
                partial_pairs.append((caption["caption_uid"], image_id, candidate["score"]))
                used_images.add(image_id)
                _search(idx + 1, used_images, running_score + candidate["score"])
                used_images.remove(image_id)
                partial_pairs.pop()

        _search(0, set(), 0.0)

        captions_by_id = {caption["caption_uid"]: caption for caption in captions}
        mapping: Dict[str, Dict[str, Any]] = {}
        for caption_id, image_id, score in best_pairs:
            caption_candidates = candidate_map.get(caption_id, [])
            alt_caption_score = max((item["score"] for item in caption_candidates if item["image_id"] != image_id), default=float("-inf"))
            alt_image_score = max((item[1] for item in image_candidate_scores.get(image_id, []) if item[0] != caption_id), default=float("-inf"))
            margin = score - max(alt_caption_score, alt_image_score)
            if score < 8.0 or (margin < 1.5 and len(caption_candidates) > 1):
                ambiguous_skips += 1
                logger.info("caption match ambiguous, skip page=%s caption=%s image=%s score=%.2f margin=%.2f", page, caption_id, image_id, score, margin)
                continue
            mapping[image_id] = captions_by_id[caption_id]
            logger.info("match page=%s caption=%s -> image=%s score=%.2f", page, captions_by_id[caption_id]["figure_id"], image_id, score)

        progress = True
        while progress:
            progress = False
            used_image_ids = set(mapping.keys())
            used_caption_ids = {caption["caption_uid"] for caption in mapping.values()}
            for caption in captions_sorted:
                caption_id = caption["caption_uid"]
                if caption_id in used_caption_ids:
                    continue
                remaining_candidates = [
                    item for item in candidate_map.get(caption_id, [])
                    if item["image_id"] not in used_image_ids and item["score"] >= 8.0
                ]
                if len(remaining_candidates) != 1:
                    continue
                candidate = remaining_candidates[0]
                image_id = candidate["image_id"]
                remaining_caption_options = [
                    cap_id for cap_id, score in image_candidate_scores.get(image_id, [])
                    if cap_id not in used_caption_ids and score >= 8.0
                ]
                if remaining_caption_options != [caption_id]:
                    continue
                image = images_by_id.get(image_id)
                if not image:
                    continue
                crossed = False
                for mapped_image_id, mapped_caption in mapping.items():
                    mapped_image = images_by_id.get(mapped_image_id)
                    if mapped_image and _pairs_cross(caption, image, mapped_caption, mapped_image):
                        crossed = True
                        break
                if crossed:
                    continue
                mapping[image_id] = captions_by_id[caption_id]
                residual_recoveries += 1
                progress = True
                logger.info(
                    "caption residual recovery page=%s caption=%s -> image=%s score=%.2f",
                    page,
                    captions_by_id[caption_id]["figure_id"],
                    image_id,
                    candidate["score"],
                )

        matched_caption_ids = {caption["caption_uid"] for caption in mapping.values()}
        self._caption_match_page_stats.append({
            "page": page,
            "images": len(images),
            "captions": len(captions),
            "candidate_pairs": candidate_pairs,
            "matched_pairs": len(mapping),
            "ambiguous_skips": ambiguous_skips,
            "crossing_rejects": crossing_rejects,
            "residual_recoveries": residual_recoveries,
            "unmatched_images": max(0, len(images) - len(mapping)),
            "unmatched_captions": max(0, len(captions) - len(matched_caption_ids)),
        })
        return mapping

    def _caption_to_image_id(self, caption_text: str, elem: Dict) -> Optional[str]:
        """从 caption 文本推断关联的图像 ID（找 caption 紧邻的上方图像）"""
        page = elem.get('page number', 1)
        bbox = elem.get('bounding box', [])
        images_on_page = [i for i in self._iter_layout_items() if i.get('type') in ('image', 'picture') and i.get('page number') == page]
        nearest = self._find_nearest_image(page, bbox, images_on_page)
        return nearest.get('image_uid') if nearest else None

    def _find_nearest_image(self, page: int, bbox: List[float], image_elems: List[Dict]) -> Optional[Dict]:
        """
        找页内位于 caption 上方的最近图像，返回距离最近的图。
        使用 _bbox_geom 统一几何语义：image.top >= caption.bottom。
        距离 = image.top - caption.bottom（方向性间隙）。
        无候选时返回 None，不做宽松 fallback。
        """
        if not bbox or len(bbox) < 4:
            return None
        cap_geom = self._bbox_geom(bbox)
        candidates = []
        max_gap = self.config.get("image_filter", {}).get("nearest_caption_image_gap", 50) if hasattr(self, "config") else 50
        for img in image_elems:
            img_bbox = img.get('bounding box', [])
            if not img_bbox or len(img_bbox) < 4:
                continue
            img_geom = self._bbox_geom(img_bbox)
            if img_geom["top"] < cap_geom["bottom"]:
                continue
            directional_gap = img_geom["top"] - cap_geom["bottom"]
            if directional_gap > max_gap:
                continue
            x_overlap = self._x_overlap_ratio(bbox, img_bbox)
            candidates.append((directional_gap, -x_overlap, img))

        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    def _match_caption(self, img_id: str, page: int, bbox: List[float], caption_map: Dict[str, Dict[str, Any]]) -> str:
        """从 caption_map 中精确匹配 image_id，找不到则返回空字符串（不做同页宽松匹配）"""
        if img_id in caption_map:
            return caption_map[img_id]['text']
        return ''

    def _parse_caption_label(self, caption: str) -> Optional[Tuple[str, int]]:
        normalized = self._normalize_heading_token_spaces(caption)
        caption_patterns = self.config.get("caption_patterns", DEFAULT_CONFIG["caption_patterns"]) if hasattr(self, "config") else DEFAULT_CONFIG["caption_patterns"]
        for figure_kind in ("sfig", "scheme", "fig"):
            for pattern in caption_patterns.get(figure_kind, []):
                match = re.match(pattern, normalized, re.IGNORECASE)
                if match:
                    return figure_kind, int(match.group(1))
        # --- Robustness fallback: handle OCR artifacts such as "Figure S3." / "Fig.S3" ---
        # Remove trailing punctuation and compact whitespace for a second-pass attempt
        cleaned = re.sub(r'[.\s]+$', '', normalized).strip()
        # Supplementary figure: Fig. S<N> / Figure S<N> / FigS<N> (no space), etc.
        m = re.match(r'^(?:supplementary\s+fig(?:ure)?\.?|fig(?:ure)?\.?\s*)S\.?\s*(\d+)\b', cleaned, re.IGNORECASE)
        if m:
            return "sfig", int(m.group(1))
        # Regular figure: Figure<N> without space (OCR spacing artifact)
        m = re.match(r'^fig(?:ure)?\.?\s*(\d+)\b', cleaned, re.IGNORECASE)
        if m:
            return "fig", int(m.group(1))
        # Scheme: Scheme<N>
        m = re.match(r'^scheme\.?\s*(\d+)\b', cleaned, re.IGNORECASE)
        if m:
            return "scheme", int(m.group(1))
        return None

    def _infer_figure_id(self, caption: str, fallback_index: int) -> str:
        parsed = self._parse_caption_label(caption or "")
        if parsed:
            figure_kind, figure_number = parsed
            return f"{figure_kind}_{figure_number:03d}"
        return f"fig_{fallback_index:03d}"

    def _find_fallback_caption(self, figure_id: str, page: int) -> str:
        if not figure_id:
            return ""
        fig_kind = "Figure"
        fig_num = ""
        if "_" in figure_id:
            parts = figure_id.rsplit("_", 1)
            fig_kind = parts[0].replace("fig", "Figure").replace("sfig", "Figure").replace("scheme", "Scheme")
            try:
                fig_num = str(int(parts[1]))
            except ValueError:
                fig_num = parts[1]
        else:
            fig_num = figure_id

        patterns = [
            re.compile(rf'(?i)\b{re.escape(fig_kind)}\s*\.?\s*{re.escape(fig_num)}\b'),
            re.compile(rf'(?i)\bFig\.\s*{re.escape(fig_num)}\b'),
            re.compile(rf'(?i)\bScheme\s*{re.escape(fig_num)}\b'),
        ]

        for sent in self.sentences if hasattr(self, 'sentences') else []:
            sent_page = getattr(sent, 'page', -1)
            if abs(sent_page - page) > 1:
                continue
            text = sent.text if hasattr(sent, 'text') else ""
            for pat in patterns:
                if pat.search(text):
                    return text.strip()[:300]

        return ""

    def _image_priority(self, image: Dict[str, Any]) -> Tuple[int, int, str]:
        reason = image.get("vlm_reason") or ""
        if reason == "caption":
            bucket = 0
        elif reason == "failed_caption_match":
            bucket = 1
        else:
            bucket = 2
        return (bucket, image.get("page", 10**6), image.get("figure_id", ""))

    def _drop_uncaptioned_figure_id_collisions(self, images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        captioned_ids = {
            str(img.get("figure_id") or "").strip()
            for img in images
            if img.get("has_caption") and str(img.get("figure_id") or "").strip()
        }
        if not captioned_ids:
            return images

        kept: List[Dict[str, Any]] = []
        dropped: List[Dict[str, Any]] = []
        for img in images:
            figure_id = str(img.get("figure_id") or "").strip()
            if not img.get("has_caption") and figure_id and figure_id in captioned_ids:
                dropped.append({
                    "figure_id": figure_id,
                    "page": img.get("page"),
                    "reason": img.get("vlm_reason") or "uncaptioned_collision",
                    "image_uid": img.get("image_uid"),
                })
                continue
            kept.append(img)

        if dropped:
            self.diagnostics["dropped_uncaptioned_figure_id_collisions"] = dropped
            logger.info("dropped %s uncaptioned images due to figure_id collisions", len(dropped))
        return kept

    def _drop_large_uncaptioned_on_captioned_pages(self, images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        captioned_pages = {
            int(img.get("page"))
            for img in images
            if img.get("has_caption") and isinstance(img.get("page"), int)
        }
        if not captioned_pages:
            return images

        kept: List[Dict[str, Any]] = []
        dropped: List[Dict[str, Any]] = []
        for img in images:
            reason = str(img.get("vlm_reason") or "")
            page = img.get("page")
            if not img.get("has_caption") and reason.startswith("large_uncaptioned(") and page in captioned_pages:
                dropped.append({
                    "figure_id": img.get("figure_id"),
                    "page": page,
                    "reason": reason,
                    "image_uid": img.get("image_uid"),
                })
                continue
            kept.append(img)

        if dropped:
            self.diagnostics["dropped_large_uncaptioned_on_captioned_pages"] = dropped
            logger.info("dropped %s large uncaptioned images on captioned pages", len(dropped))
        return kept

    # ---------- 表格检测与任务构建 (P4 升级版) ----------

    # ---- 表格类型分类关键词 ----
    _TABLE_TYPE_KEYWORDS: Dict[str, List[str]] = {
        "kinetics_parameters": [
            r'\bkm\b', r'\bvmax\b', r'\bvm\b', r'\bkcat\b', r'\bk_cat\b',
            r'\bmichaelis', r'\blineweaver', r'\bkinetic\s+param',
            r'\bcatalytic\s+effici', r'\bspecific\s+activ',
            r'\bturnover', r'\bsteady[- ]state',
        ],
        "electronic_structure": [
            r'\beg\s+occupancy\b', r'\beg\s+electron', r'\boxidation\s+state',
            r'\bvalence\s+state', r'\boxygen\s+vacanc', r'\bspin\s+state',
            r'\bb[- ]o\s+covalency', r'\bO\s+2p[- ]band', r'\badsorption\s+energy',
            r'\bcharge\s+transfer', r'\belectron\s+transfer', r'\bXAFS\b', r'\bXANES\b',
            r'\bEXAFS\b', r'\bDFT\b', r'\bband\s+gap',
        ],
        "material_surface_properties": [
            r'\bBET\b', r'\bsurface\s+area', r'\bpore\s+size', r'\bpore\s+volume',
            r'\bparticle\s+size', r'\bzeta\s+potential', r'\bhydrodynamic',
            r'\bBJH\b', r'\btexture', r'\bporosity',
        ],
        "composition": [
            r'\bICP\b', r'\bICP[- ]OES\b', r'\bICP[- ]MS\b', r'\bICP[- ]AES\b',
            r'\belemental\s+anal', r'\bcomposition\b', r'\bloading\b',
            r'\bmolar\s+ratio', r'\bwt\s*%', r'\batomic\s*%', r'\bEDS\b', r'\bEDX\b',
        ],
        "sensing_performance": [
            r'\bLOD\b', r'\bdetection\s+limit', r'\blinear\s+rang', r'\bsensitiv',
            r'\bselectiv', r'\brecovery\b', r'\binterfer', r'\bsignal\s+to[- ]noise',
        ],
        "application_performance": [
            r'\bcell\s+viabilit', r'\btumou?r\b', r'\bantibacterial\b',
            r'\bwound\s+heal', r'\bsurvival\b', r'\bROS\s+scaveng',
            r'\bdegradation\b', r'\bantioxidant\b', r'\bcytotoxic',
            r'\bin\s+vivo\b', r'\bin\s+vitro\b',
        ],
    }

    # ---- 表格预期 schema ----
    _TABLE_EXPECTED_SCHEMAS: Dict[str, List[str]] = {
        "kinetics_parameters": [
            "material", "enzyme_like_activity", "substrate",
            "Km_value", "Km_unit", "Vmax_value", "Vmax_unit",
            "kcat_value", "kcat_unit", "specific_activity_value", "specific_activity_unit",
            "assay_pH", "temperature", "buffer",
            "source_table_id", "source_page",
        ],
        "electronic_structure": [
            "material", "oxidation_state", "oxygen_vacancy",
            "eg_occupancy", "spin_state", "B_O_covalency",
            "adsorption_energy", "method",
            "source_table_id", "source_page",
        ],
        "material_surface_properties": [
            "material", "BET_surface_area", "BET_unit",
            "pore_size", "pore_size_unit",
            "particle_size", "particle_size_unit",
            "source_table_id", "source_page",
        ],
        "composition": [
            "material", "element", "measured_value", "unit", "method",
            "source_table_id", "source_page",
        ],
        "sensing_performance": [
            "material", "target_analyte", "LOD_value", "LOD_unit",
            "linear_range_low", "linear_range_high", "linear_range_unit",
            "sensitivity", "selectivity_notes",
            "source_table_id", "source_page",
        ],
        "application_performance": [
            "material", "application_type", "model_system",
            "key_metric", "key_value", "key_unit",
            "source_table_id", "source_page",
        ],
        "general_table": [
            "material", "key_parameter", "value", "unit",
            "source_table_id", "source_page",
        ],
    }

    def _detect_tables(self) -> List[Dict[str, Any]]:
        """
        从 parser JSON 中检测 table 元素，返回完整表格信息列表。
        递归搜索嵌套 kids，兼容多种 parser 输出格式。
        """
        return self._extract_tables_from_kids(self.kids)

    def _extract_tables_from_kids(
        self, kids: List[Any], parent_page: int = 1
    ) -> List[Dict[str, Any]]:
        """
        递归从 kids 中提取所有表格，兼容：
        1. type == "table"，有 rows/cells
        2. type == "table"，只有 content/text
        3. 段落包含 "Table N / Table SN" caption（文本型表格）
        4. SI 里实际表格（同上）
        """
        tables: List[Dict[str, Any]] = []

        def _build_table_from_elem(elem: Dict[str, Any], page: int) -> Optional[Dict[str, Any]]:
            """从单个元素构建表格字典，返回 None 表示不是表格"""
            elem_type = str(elem.get("type", "")).lower()
            rows_raw = elem.get("rows")
            has_rows = isinstance(rows_raw, list) and len(rows_raw) > 0

            # 形态 1 & 2：type == "table"
            if elem_type == "table" or has_rows:
                cells_data: List[List[str]] = []
                columns: List[str] = []

                if has_rows:
                    for row_idx, row in enumerate(rows_raw):
                        if not isinstance(row, dict):
                            continue
                        row_cells = row.get("cells", [])
                        cell_texts: List[str] = []
                        for cell in row_cells:
                            if isinstance(cell, dict):
                                ct = self._normalize_text(
                                    cell.get("content", "") or cell.get("text", "")
                                )
                                if not ct:
                                    cell_kids = cell.get("kids", [])
                                    if isinstance(cell_kids, list):
                                        ct = " ".join(
                                            self._normalize_text(ck.get("content", ""))
                                            for ck in cell_kids if isinstance(ck, dict)
                                        ).strip()
                                cell_texts.append(ct)
                            elif isinstance(cell, str):
                                cell_texts.append(self._normalize_text(cell))
                        if cell_texts:
                            cells_data.append(cell_texts)
                            if row_idx == 0:
                                columns = cell_texts  # 第一行作为列名

                raw_text = self._normalize_text(
                    elem.get("content", "") or elem.get("text", "") or ""
                )
                if not raw_text and cells_data:
                    raw_text = "\n".join(" | ".join(row) for row in cells_data)

                caption = self._normalize_text(
                    elem.get("caption", "") or elem.get("title", "") or ""
                )
                bbox = elem.get("bbox") or elem.get("bounding_box") or []

                return {
                    "source": "structured",
                    "caption": caption,
                    "text": raw_text,
                    "cells": cells_data,
                    "columns": columns,
                    "page": elem.get("page number", page) or page,
                    "bbox": bbox,
                    "kid_ids": [elem.get("id")] if elem.get("id") is not None else [],
                    "image_path": elem.get("image_path") or elem.get("image") or "",
                    "has_rows": has_rows,
                    "has_columns": len(columns) > 0,
                }

            # 形态 3：段落型表格（含 Table N / Table SN caption）
            if elem_type in ("paragraph", "text", "caption", ""):
                content = self._normalize_text(
                    elem.get("content", "") or elem.get("text", "") or ""
                )
                if content and self._is_table_caption_line(content):
                    return {
                        "source": "caption_paragraph",
                        "caption": content,
                        "text": content,
                        "cells": [],
                        "columns": [],
                        "page": elem.get("page number", page) or page,
                        "bbox": elem.get("bbox") or [],
                        "kid_ids": [elem.get("id")] if elem.get("id") is not None else [],
                        "image_path": "",
                        "has_rows": False,
                        "has_columns": False,
                    }

            return None

        def _scan_recursive(items: List[Any], depth: int = 0) -> None:
            for elem in items:
                if not isinstance(elem, dict):
                    continue
                page = elem.get("page number", parent_page) or parent_page
                tbl = _build_table_from_elem(elem, page)
                if tbl is not None:
                    tables.append(tbl)
                    # 不再递归进入已识别的表格元素
                    continue
                nested_kids = elem.get("kids")
                if isinstance(nested_kids, list) and nested_kids and depth < 8:
                    _scan_recursive(nested_kids, depth + 1)

        _scan_recursive(kids)
        return tables

    def _is_table_caption_line(self, text: str) -> bool:
        """判断文本行是否是表格标题行"""
        TABLE_CAPTION_PAT = re.compile(
            r'(?i)^\s*(?:supplementary\s+)?(?:table|tbl\.?)\s+(?:S?\d+|[A-Z]\d*)\b',
        )
        return bool(TABLE_CAPTION_PAT.match(text.strip()))

    def _find_table_captions(self, kids: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """
        从 kids 中查找独立的表格标题行（常见于 Elsevier/RSC 解析结果）。
        返回 list of {text, page, kid_id}
        """
        captions: List[Dict[str, Any]] = []
        scan_kids = kids if kids is not None else self.kids

        def _scan(items: List[Any]) -> None:
            for elem in items:
                if not isinstance(elem, dict):
                    continue
                content = self._normalize_text(
                    elem.get("content", "") or elem.get("text", "") or ""
                )
                if content and self._is_table_caption_line(content):
                    captions.append({
                        "text": content,
                        "page": elem.get("page number", 1),
                        "kid_id": elem.get("id"),
                    })
                nested = elem.get("kids")
                if isinstance(nested, list):
                    _scan(nested)

        _scan(scan_kids)
        return captions

    def _associate_table_caption(
        self, table: Dict[str, Any], captions: List[Dict[str, Any]]
    ) -> str:
        """
        将已有的 captions 列表中的标题关联到指定表格。
        关联策略：同页优先，距离最近（页码差最小）。
        """
        if table.get("caption"):
            return table["caption"]
        table_page = table.get("page", 1)
        best_cap = ""
        best_dist = 99999
        for cap in captions:
            dist = abs((cap.get("page") or 1) - table_page)
            if dist < best_dist:
                best_dist = dist
                best_cap = cap["text"]
        return best_cap if best_dist <= 2 else ""

    def _table_to_markdown(self, table: Dict[str, Any]) -> str:
        """将表格转为 Markdown 格式文本"""
        cells = table.get("cells", [])
        if not cells:
            return table.get("text", "")

        lines: List[str] = []
        for row_idx, row in enumerate(cells):
            line = "| " + " | ".join(str(c) for c in row) + " |"
            lines.append(line)
            if row_idx == 0:
                sep = "| " + " | ".join("---" for _ in row) + " |"
                lines.append(sep)
        return "\n".join(lines)

    def _classify_table_type(self, caption: str, content: str) -> str:
        """
        按 caption + content 文本通用分类表格类型。
        不写特定表格编号。
        """
        combined = (caption + " " + content).lower()
        for ttype, patterns in self._TABLE_TYPE_KEYWORDS.items():
            for pat in patterns:
                if re.search(pat, combined, re.IGNORECASE):
                    return ttype
        return "general_table"

    def _score_table_priority(self, table: Dict[str, Any]) -> float:
        """计算表格优先级分数。高价值科学数据表格得高分。"""
        caption = table.get("caption", "")
        content = table.get("text", "") or ""
        cells = table.get("cells", [])
        content_text = content
        if cells and not content_text:
            content_text = "\n".join(" | ".join(r) for r in cells)

        combined = caption + " " + content_text
        score = 0.0
        ttype = table.get("table_type", self._classify_table_type(caption, content_text))

        # 表格类型基础分
        type_base_scores = {
            "kinetics_parameters": 10.0,
            "electronic_structure": 9.0,
            "material_surface_properties": 7.0,
            "composition": 6.0,
            "sensing_performance": 8.0,
            "application_performance": 7.0,
            "general_table": 2.0,
        }
        score += type_base_scores.get(ttype, 2.0)

        # 包含数值加分
        if re.search(r'\d+\.\d+', combined):
            score += 3.0
        # 有多行数据加分
        row_count = len(cells) if cells else (content_text.count('\n') + 1)
        if row_count >= 3:
            score += 2.0
        if row_count >= 6:
            score += 2.0
        # 内容丰富加分
        if len(content_text) > 300:
            score += 2.0
        # 有标题
        if caption:
            score += 1.0
        # SI 表格（caption 含 S 编号）适度降权，但 kinetics/electronic_structure 除外
        if re.search(r'(?i)\btable\s+S\d+\b', caption):
            if ttype in ("kinetics_parameters", "electronic_structure", "sensing_performance"):
                pass  # 高价值 SI 表格不降权
            else:
                score -= 1.0
        return round(score, 2)

    def _build_table_extraction_task(
        self, tables: List[Dict[str, Any]], is_supplementary: bool = False
    ) -> Dict[str, Any]:
        """
        构建完整的 table_extraction_task，
        包括 prompt_template 和筛选后的 tables 列表。
        """
        # 配额：主文献最多 8 个，SI 最多 20 个
        max_tables = 20 if is_supplementary else 8
        table_items: List[Dict[str, Any]] = []

        for idx, tbl in enumerate(tables, start=1):
            caption = tbl.get("caption", "")
            cells = tbl.get("cells", [])
            content_text = tbl.get("text", "") or ""
            if cells and not content_text:
                content_text = "\n".join(" | ".join(r) for r in cells)

            ttype = self._classify_table_type(caption, content_text)
            priority = self._score_table_priority({**tbl, "table_type": ttype})
            markdown = self._table_to_markdown(tbl)

            has_rows = bool(cells) and len(cells) >= 1
            has_cols = bool(tbl.get("columns"))
            row_count = len(cells) if cells else 0
            col_count = len(cells[0]) if cells else 0
            needs_vlm = (
                not has_rows
                and (bool(tbl.get("image_path")) or bool(tbl.get("bbox")))
                and len(content_text.strip()) < 100
            )
            parser_conf = "high" if has_rows and row_count >= 2 else (
                "medium" if content_text else "low"
            )

            table_items.append({
                "table_id": f"table_{idx:03d}",
                "source_file": str(self.json_path.name),
                "page": tbl.get("page", 1),
                "caption": caption,
                "table_type": ttype,
                "priority_score": priority,
                "rows": cells,
                "columns": tbl.get("columns", []),
                "content_text": content_text,
                "markdown": markdown,
                "expected_schema": self._TABLE_EXPECTED_SCHEMAS.get(ttype, []),
                "source_kid_ids": tbl.get("kid_ids", []),
                "bbox": tbl.get("bbox", []),
                "quality": {
                    "has_rows": has_rows,
                    "has_columns": has_cols,
                    "row_count": row_count,
                    "col_count": col_count,
                    "parser_confidence": parser_conf,
                    "needs_vlm_fallback": needs_vlm,
                    "reason": "no_structured_rows" if not has_rows else "",
                },
            })

        # 按优先级降序排列，然后按配额截取
        table_items.sort(key=lambda t: t["priority_score"], reverse=True)

        # 高价值表格全保，低价值表格截配额
        high = [t for t in table_items if t["priority_score"] >= 7.0]
        medium = [t for t in table_items if 4.0 <= t["priority_score"] < 7.0]
        low = [t for t in table_items if t["priority_score"] < 4.0]

        selected: List[Dict[str, Any]] = []
        selected.extend(high)
        remaining = max_tables - len(selected)
        if remaining > 0:
            selected.extend(medium[:remaining])
        remaining = max_tables - len(selected)
        if remaining > 0:
            selected.extend(low[:remaining])
        selected = selected[:max_tables]

        # 诊断日志
        skipped_count = len(table_items) - len(selected)
        for tbl in selected:
            logger.info(
                "table included: id=%s type=%s priority=%.1f page=%d caption=%.60s needs_vlm=%s",
                tbl["table_id"], tbl["table_type"], tbl["priority_score"],
                tbl["page"], tbl["caption"] or "(no caption)",
                tbl["quality"]["needs_vlm_fallback"],
            )
        for tbl in table_items:
            if tbl not in selected:
                logger.debug(
                    "table skipped: id=%s type=%s priority=%.1f page=%d caption=%.50s",
                    tbl["table_id"], tbl["table_type"], tbl["priority_score"],
                    tbl["page"], tbl["caption"] or "(no caption)",
                )

        # 构建 VLM fallback 任务
        vlm_fallback_tasks: List[Dict[str, Any]] = []
        for tbl in selected:
            if tbl["quality"]["needs_vlm_fallback"] and tbl.get("bbox"):
                vlm_fallback_tasks.append({
                    "task_type": "table_vlm_fallback",
                    "table_id": tbl["table_id"],
                    "page": tbl["page"],
                    "bbox": tbl["bbox"],
                    "caption": tbl["caption"],
                    "table_type": tbl["table_type"],
                    "prompt": (
                        "This is a screenshot of a scientific table. "
                        "Please extract all rows and columns as structured data. "
                        "Return JSON with keys: rows (list of lists), columns (list of column names). "
                        "Preserve all numeric values and units exactly."
                    ),
                })

        type_counts: Dict[str, int] = {}
        for t in selected:
            type_counts[t["table_type"]] = type_counts.get(t["table_type"], 0) + 1

        # TABLE_EXTRACTION_PROMPT_TEMPLATE
        prompt_template = (
            "You are extracting structured nanozyme data from parsed scientific tables.\n"
            "Do not summarize the table. Extract row-level records.\n"
            "Preserve units exactly. If a value is missing, use null.\n"
            "Do not infer values not present in the table.\n"
            "Every record must include source_table_id and source_page.\n\n"
            "Return strict JSON:\n"
            '{\n'
            '  "records": [\n'
            '    {\n'
            '      "record_type": "kinetics_parameters | electronic_structure | material_property | composition | sensing_performance | application_performance | other",\n'
            '      "material": null,\n'
            '      "enzyme_like_activity": null,\n'
            '      "substrate": null,\n'
            '      "Km_value": null,\n'
            '      "Km_unit": null,\n'
            '      "Vmax_value": null,\n'
            '      "Vmax_unit": null,\n'
            '      "kcat_value": null,\n'
            '      "kcat_unit": null,\n'
            '      "specific_activity_value": null,\n'
            '      "specific_activity_unit": null,\n'
            '      "assay_condition": {\n'
            '        "pH": null,\n'
            '        "temperature": null,\n'
            '        "buffer": null,\n'
            '        "H2O2_concentration": null,\n'
            '        "TMB_concentration": null\n'
            '      },\n'
            '      "other_parameters": {},\n'
            '      "source_table_id": "...",\n'
            '      "source_page": 0,\n'
            '      "evidence_text": "..."\n'
            '    }\n'
            '  ],\n'
            '  "warnings": []\n'
            '}'
        )

        return {
            "prompt_template": prompt_template,
            "tables": selected,
            "vlm_fallback_tasks": vlm_fallback_tasks,
            "stats": {
                "total_detected": len(table_items),
                "total_selected": len(selected),
                "skipped": skipped_count,
                "high_priority": len(high),
                "medium_priority": len(medium),
                "low_priority": len(low),
                "table_types_count": type_counts,
                "needs_vlm_fallback_count": sum(
                    1 for t in selected if t["quality"]["needs_vlm_fallback"]
                ),
            },
        }

    def _build_table_tasks(self, tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        向后兼容入口：构建 table_task 列表（旧版接口）。
        在新流程中，_build_table_extraction_task 是主入口。
        """
        is_si = getattr(self, "document_kind", "main") == "supplementary"
        result: List[Dict[str, Any]] = []
        for idx, table in enumerate(tables, start=1):
            caption = table.get("caption", "").strip()
            cells = table.get("cells", [])
            content_text = table.get("text", "") or ""
            if cells and not content_text:
                content_text = "\n".join(" | ".join(row) for row in cells)
            if not caption:
                lines = content_text.split("\n")
                if lines:
                    caption = lines[0].strip()
            if not content_text.strip():
                continue
            ttype = self._classify_table_type(caption, content_text)
            score = self._score_table_priority({
                "caption": caption, "text": content_text,
                "cells": cells, "table_type": ttype,
            })
            result.append({
                "table_id": f"table_{idx:03d}",
                "caption": caption,
                "content_text": content_text,
                "table_type": ttype,
                "priority_score": round(score, 2),
                "source_page": table.get("page", 1),
                "markdown": self._table_to_markdown(table),
                "expected_schema": self._TABLE_EXPECTED_SCHEMAS.get(ttype, []),
                "quality": {
                    "has_rows": bool(cells),
                    "has_columns": bool(table.get("columns")),
                    "row_count": len(cells),
                    "col_count": len(cells[0]) if cells else 0,
                    "parser_confidence": "high" if cells else "low",
                    "needs_vlm_fallback": (
                        not cells
                        and bool(table.get("image_path") or table.get("bbox"))
                        and len(content_text.strip()) < 100
                    ),
                    "reason": "",
                },
            })
        result.sort(key=lambda t: t["priority_score"], reverse=True)
        return result

    def _clean_table_references(self, text: str) -> str:
        return re.sub(r'\s*\[\d+\]\s*', ' ', text)

    def _build_table_context_hint(self, text: str) -> str:
        lines = text.strip().split('\n')
        if not lines:
            return "[Table Context: empty table]"
        first_row = lines[0]
        columns = [c.strip() for c in first_row.split('|') if c.strip()]
        col_names = ', '.join(columns[:8])
        data_rows = max(0, len(lines) - 1)
        return f"[Table Context: {col_names}, {data_rows} rows. Extract structured data: material names, substrates, Km/Vmax values, LOD, linear range as applicable.]"

    # ---------- Metadata fallback (P1) ----------
    def _extract_title_from_pages(self) -> str:
        """当顶层 metadata.title 为空时，从 page-1 kids 中提取 title。"""
        title_keywords = [
            r"(?i)\bnanozyme", r"(?i)\bnanoparticle", r"(?i)\bcatal",
            r"(?i)\bperoxidase", r"(?i)\boxidase", r"(?i)\bactivity",
            r"(?i)\bsensing", r"(?i)\btherapy", r"(?i)\bdetection",
        ]
        best_title = ""
        best_score = -999.0
        for elem in self._iter_layout_items():
            if elem.get("page number", 1) != 1:
                continue
            text = self._normalize_text(elem.get("content", ""))
            if not text or len(text) < 10:
                continue
            kid_type = str(elem.get("type", "")).lower()
            block_type = str(elem.get("blockType", ""))
            # 排除 subtitle（通常是作者行）
            if kid_type == "subtitle":
                continue
            score = len(text)
            # 关键词加分
            for pat in title_keywords:
                if re.search(pat, text):
                    score += 10
            # doctitle / Title 类型压倒性优先
            if kid_type == "doctitle" or block_type == "Title":
                score += 1000
            # 段落类型 + 含大量逗号+人名特征 → 可能是作者行，降分
            if kid_type == "paragraph":
                comma_count = text.count(",")
                uppercase_words = len(re.findall(r"\b[A-Z][a-z]+\b", text))
                if comma_count >= 3 and uppercase_words >= 4:
                    score -= 200
            if self._is_junk_title(text):
                continue
            if score > best_score:
                best_score = score
                best_title = text
        return best_title

    def _extract_authors_from_pages(self) -> str:
        """当顶层 metadata.author 为空时，从 page-1 kids 中提取作者。"""
        author_candidates: List[Tuple[float, str]] = []
        for elem in self._iter_layout_items():
            if elem.get("page number", 1) != 1:
                continue
            text = self._normalize_text(elem.get("content", ""))
            if not text or len(text) < 5:
                continue
            kid_type = str(elem.get("type", "")).lower()
            score = 0.0
            # subtitle 类型优先作为作者来源
            if kid_type == "subtitle":
                score += 100
            # 人名特征检测：多个大写单词以逗号分隔
            comma_count = text.count(",")
            uppercase_words = len(re.findall(r"\b[A-Z][a-z]+\b", text))
            if comma_count >= 2 and uppercase_words >= 3:
                score += 50
            # 含 "and" 分隔的名字
            if re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\s+and\s+[A-Z]", text):
                score += 30
            # 含作者标记
            if re.search(r"[†‡*]+", text):
                score += 20
            # 排除明显不是作者的内容
            if self._is_junk_title(text):
                continue
            if re.search(r"(?i)\b(abstract|introduction|keywords)\b", text):
                continue
            if score > 10:  # 只保留有一定作者特征的候选
                author_candidates.append((score, text))
        if not author_candidates:
            return ""
        author_candidates.sort(key=lambda x: x[0], reverse=True)
        return author_candidates[0][1]

    # ---------- References 过滤增强 (P2) ----------
    def _detect_ref_section_page(self, blocks: List[BlockInfo]) -> Optional[int]:
        ref_page = None
        for block in blocks:
            if block.kind == "heading" and self._is_reference_section(block.text):
                ref_page = block.page
                break
        if ref_page is None:
            for block in blocks:
                if self._is_reference_section(block.text):
                    ref_page = block.page
                    break
        if ref_page is None and hasattr(self, 'data'):
            for kid in self._iter_layout_items(self.data.get("kids", [])):
                if isinstance(kid, dict):
                    kid_type = str(kid.get("type", "")).lower()
                    content = str(kid.get("content", "")).strip()
                    if kid_type == "heading" and re.search(r"(?i)\breferences?\b", content):
                        ref_page = kid.get("page number")
                        if ref_page is not None:
                            break
        return ref_page

    def _is_reference_section(self, text) -> bool:
        """判断是否为参考文献章节标题，支持纯文本或 kid dict。"""
        if isinstance(text, dict):
            kid_type = str(text.get("type", "")).lower()
            content = self._normalize_text(text.get("content", ""))
            if kid_type == "heading" and re.search(r"(?i)\breference", content):
                return True
            text = content
        if not isinstance(text, str):
            return False
        stripped = text.strip()
        if not stripped:
            return False
        first_line = stripped.split("\n")[0].strip().lower()
        ref_starts = [
            "references", "reference", "bibliography",
            "literature cited", "cited literature",
        ]
        return any(first_line.startswith(rs) for rs in ref_starts)

    def _is_reference_entry(self, sentence: str) -> bool:
        """判断单个句子是否看起来像完整引用条目（编号+作者-期刊-年份模式），也检测无编号条目。"""
        s = sentence.strip()
        has_numbering = bool(
            re.match(r'^\s*\[\d+\]', s)
            or re.match(r'^\s*\d{1,3}\.\s+[A-Z]', s)
            or re.match(r'^\s*\(\d+\)\s+', s)
            or re.match(r'^\s*[¹²³⁴⁵⁶⁷⁸⁹⁰]+\s+', s)
            or re.match(r'^\s*\d{1,3},\s+[A-Z]', s)
        )
        features = 0
        if re.search(r'\bet al\.?\b', s, re.IGNORECASE):
            features += 1
        if re.search(r'\b(?:19|20)\d{2}\b', s):
            features += 1
        if re.search(r'\b\d+\s*[,–-]\s*\d+\b', s):
            features += 1
        if re.search(r'(?i)\b(?:J\.|Chem\.|Phys\.|Nano|Angew|ACS|Nature|Science|Adv\.|Mater\.|Lett\.)\b', s):
            features += 1
        if re.search(r'10\.\d{4,}/', s):
            features += 1
        if re.match(r'^[A-Z][a-z]+,\s*[A-Z]\.(?:\s*[A-Z]\.)?,?\s', s):
            features += 1
        if has_numbering:
            return features >= 1
        return features >= 3

    def _filter_reference_sentences(self, sentences: List[str]) -> List[str]:
        """过滤掉参考文献类句子，保留正常讨论句。"""
        # 编号引用模式
        numbered_ref_patterns = [
            re.compile(r'^\s*\[\d+\]'),
            re.compile(r'^\s*\d{1,3}\.\s+[A-Z]'),
            re.compile(r'^\s*\(\d+\)\s+'),
        ]
        # Author et al., Year 和 DOI 模式
        author_year_pattern = re.compile(r'\b[A-Z][a-z]+\s+et\s+al\.?,?\s*(?:19|20)\d{2}')
        doi_pattern = re.compile(r'10\.\d{4,}/\S+')

        # 期刊+年份+卷页模式（需同时匹配多个特征才过滤）
        journal_pattern = re.compile(
            r'(?i)\b(?:J\.|Chem\.|Phys\.|Nano|Angew|ACS|Nature|Science|Adv\.|Mater\.|Lett\.|'
            r'Anal\.|Biochem\.|Environ\.|Inorg\.|Org\.|Proc\.|Rev\.|Soc\.|Int\.)\b'
        )
        vol_page_pattern = re.compile(r'(?:,\s*vol\.?|,\s*pp\.?|\b\d+\s*[,–-]\s*\d+)')
        year_pattern = re.compile(r'\b(?:19|20)\d{2}\b')

        filtered: List[str] = []
        for s in sentences:
            # 编号引用：直接过滤
            if any(pat.search(s) for pat in numbered_ref_patterns):
                # 需同时有作者/年份特征才过滤，避免误伤
                if author_year_pattern.search(s) or doi_pattern.search(s) or year_pattern.search(s):
                    continue
            # Author et al. + DOI 同时出现
            if author_year_pattern.search(s) and doi_pattern.search(s):
                continue
            # 引用标题+期刊模式：需至少2个特征同时匹配
            ref_features = 0
            if journal_pattern.search(s):
                ref_features += 1
            if vol_page_pattern.search(s):
                ref_features += 1
            if year_pattern.search(s):
                ref_features += 1
            if author_year_pattern.search(s):
                ref_features += 1
            if doi_pattern.search(s):
                ref_features += 1
            if ref_features >= 3:
                continue
            filtered.append(s)
        return filtered

    def _collect_high_value_sentences(self, sentences: List[SentenceInfo]) -> List[SentenceInfo]:
        """在 reference section gate 之外，增加 per-sentence 兜底引用条目检查和 page-level gate。"""
        result: List[SentenceInfo] = []
        in_ref_section = False
        ref_page = getattr(self, '_ref_section_page', None)
        for sent in sentences:
            # Section-level gate
            if self._is_reference_section(sent.text):
                in_ref_section = True
                continue
            if in_ref_section:
                continue
            # Page-level gate: filter sentences on/after reference section page
            if ref_page is not None and sent.page > ref_page:
                continue
            if ref_page is not None and sent.page == ref_page:
                if sent.section in ("unknown", "metadata", "backmatter") or self._is_reference_entry(sent.text):
                    continue
            # Per-sentence 兜底：看起来像完整引用条目也排除
            if self._is_reference_entry(sent.text):
                continue
            result.append(sent)
        return result

    # ---------- 图像排序增强 (P6-SI) ----------
    def _rank_images(self, images: List[Dict[str, Any]], is_supplementary: bool = False) -> List[Dict[str, Any]]:
        """对图像进行排序打分，支持主文/SI 两套权重，使用 caption_type 分类。"""
        if is_supplementary:
            caption_type_bonus = {
                "kinetics_caption": 30,
                "mechanism_caption": 20,
                "application_caption": 25,
                "comparison_caption": 25,
                "morphology_caption": 3,
                "general": 8,
                "unknown": 5,
            }
            table_figure_bonus = 25
        else:
            caption_type_bonus = {
                "kinetics_caption": 20,
                "mechanism_caption": 10,
                "application_caption": 15,
                "comparison_caption": 12,
                "morphology_caption": 8,
                "general": 5,
                "unknown": 3,
            }
            table_figure_bonus = 5

        ranked: List[Dict[str, Any]] = []
        for img in images:
            caption = img.get("caption", "") or ""
            bonus = 0.0
            task_type = img.get("elem_type", "image")

            if re.search(r'(?i)\bTable\b', caption):
                task_type = "table_figure"
                bonus += table_figure_bonus

            caption_type = self._classify_caption_type(caption)
            bonus += caption_type_bonus.get(caption_type, 5)

            if caption_type == "morphology_caption":
                if is_supplementary:
                    bonus -= 5

            img_copy = dict(img)
            img_copy["_rank_score"] = bonus
            img_copy["task_type"] = task_type
            img_copy["caption_type"] = caption_type
            ranked.append(img_copy)

        ranked.sort(key=lambda x: x.get("_rank_score", 0), reverse=True)
        return ranked

    # ---------- 输出中间 JSON ----------
    def to_mid_json(self, save_path: Optional[str] = None) -> Dict:
        """生成中间任务JSON，输出 canonical multi-system 所需上下文"""
        prompt_template = self._build_prompt_template()
        chunks = getattr(self, "chunks", None) or [
            "\n".join(self._format_sentence_line(sentence) for sentence in chunk)
            for chunk in getattr(self, "chunk_sentence_groups", [])
        ] or ([self.refined_text] if self.refined_text else [])
        chunk_contexts = getattr(self, "chunk_contexts", None) or []

        llm_task = {
            "prompt_template": prompt_template,
            "chunks": chunks,
            "chunk_contexts": chunk_contexts,
        }

        vlm_tasks = []
        # Build figure_label → relevant body sentences index for body_context injection
        _body_sentences_by_label: Dict[str, List[str]] = defaultdict(list)
        _body_sentences_by_page: Dict[int, List[str]] = defaultdict(list)
        for sent in getattr(self, 'sentences', []):
            if sent.source_kind == "caption":
                continue  # skip captions themselves
            if sent.figure_label:
                _body_sentences_by_label[sent.figure_label].append(sent.normalized_text or sent.text)
            _body_sentences_by_page[sent.page].append(sent.normalized_text or sent.text)

        for img in self.images:
            reason = img.get("vlm_reason")
            if reason is None and "vlm_reason" in img:
                continue
            caption = img.get("caption", "")
            vlm_task_entry = {
                "figure_id": img.get("figure_id"),
                "image_path": img.get("image_path") or img.get("original_path"),
                "caption": caption,
                "description": img.get("description", ""),
                "page": img.get("page", 0),
                "vlm_reason": reason,
                "elem_type": img.get("elem_type", "image"),
            }
            caption_type = self._classify_caption_type(caption)
            vlm_task_entry["caption_type"] = caption_type
            # Attach up to 3 relevant body sentences as body_context
            # Priority: sentences that reference this figure_id, then same-page sentences
            fig_id = img.get("figure_id") or ""
            fig_label = fig_id  # fig_id is already in fig_xxx format
            related_sents = _body_sentences_by_label.get(fig_label, [])
            if not related_sents:
                img_page = img.get("page", 0)
                related_sents = _body_sentences_by_page.get(img_page, [])
            # Filter to most informative: prefer activity/kinetics signal sentences
            kinetics_sents = [s for s in related_sents if self._detect_kinetics_signal(s or "")]
            activity_sents = [s for s in related_sents if self._detect_activity_signal(s or "")]
            chosen = list(dict.fromkeys(kinetics_sents[:2] + activity_sents[:1] + related_sents[:2]))[:3]
            if chosen:
                vlm_task_entry["body_context"] = " | ".join(chosen)
            vlm_tasks.append(vlm_task_entry)

        chunking_mode = "multi" if len(self.chunks) > 1 else "single"

        # 排序 vlm_tasks（P6: SI 图表排序）
        is_si = getattr(self, "document_kind", "main") == "supplementary"
        if vlm_tasks:
            ranked = self._rank_images(vlm_tasks, is_supplementary=is_si)
            vlm_tasks = ranked

        table_tasks = getattr(self, "_table_tasks", []) or []

        detected_enzyme_types = set()
        detected_assay_types = set()
        has_kinetics = False
        has_application = False
        all_system_mentions: List[str] = []
        all_enzyme_mentions: List[str] = []
        all_substrate_mentions: List[str] = []
        all_application_mentions: List[str] = []
        kinetics_signal_count = 0
        material_signal_count = 0
        caption_count = 0
        for sent in self.sentences if hasattr(self, 'sentences') else []:
            tags = getattr(sent, 'value_tags', [])
            text_lower = sent.text.lower() if hasattr(sent, 'text') else ""
            if 'activity' in tags:
                for _etype, _meta in ENZYME_REGISTRY.items():
                    if _meta["keywords"][0] in text_lower:
                        detected_enzyme_types.add(EnzymeType.normalize_canonical(_etype.value))
            if 'assay' in tags:
                detected_assay_types.add('assay')
            if 'kinetics' in tags:
                has_kinetics = True
            if 'application' in tags:
                has_application = True
            all_system_mentions = self._merge_unique(all_system_mentions, self._extract_candidate_system_mentions(sent.text, sent.value_tags))
            all_enzyme_mentions = self._merge_unique(all_enzyme_mentions, sent.candidate_enzyme_mentions)
            all_substrate_mentions = self._merge_unique(all_substrate_mentions, sent.candidate_substrate_mentions)
            all_application_mentions = self._merge_unique(all_application_mentions, sent.candidate_application_mentions)
            if sent.contains_kinetics_signal:
                kinetics_signal_count += 1
            if sent.contains_material_signal:
                material_signal_count += 1
            if sent.source_kind == "caption":
                caption_count += 1

        extracted_hints = {
            "document_kind": getattr(self, "document_kind", "main"),
            "detected_enzyme_types": sorted(detected_enzyme_types),
            "multi_enzyme": len(detected_enzyme_types) >= 2,
            "detected_assay_types": sorted(detected_assay_types),
            "has_kinetics_data": has_kinetics,
            "has_application_content": has_application,
            "has_tables": bool(getattr(self, "_table_tasks", [])),
            "candidate_system_mentions": all_system_mentions[:10],
            "candidate_enzyme_mentions": all_enzyme_mentions[:8],
            "candidate_substrate_mentions": all_substrate_mentions[:8],
            "candidate_application_mentions": all_application_mentions[:6],
        }

        sentence_metadata: Dict[str, Dict[str, Any]] = {}
        for sent in self.sentences if hasattr(self, 'sentences') else []:
            if not sent.sentence_id:
                continue
            sentence_metadata[sent.sentence_id] = {
                "kid_ids": list(sent.kid_ids) if sent.kid_ids else [],
                "bbox": list(sent.bbox) if sent.bbox else None,
                "raw_text": getattr(sent, '_raw_text', sent.text or ""),
                "normalized_text": sent.normalized_text or "",
                "search_text": getattr(sent, '_search_text', ""),
                "page": sent.page,
                "section": sent.section or "",
                "source_kind": sent.source_kind or "text",
                "block_id": sent.block_id or "",
            }

        mid_json = {
        "metadata": getattr(self, "paper_metadata", None) or self._extract_document_metadata(),
        "extracted_hints": extracted_hints,
        "sentence_metadata": sentence_metadata,
        "llm_task": llm_task,
        "vlm_tasks": vlm_tasks,
        "table_tasks": table_tasks,
        "table_extraction_task": getattr(self, "_table_extraction_task", {}) or {},
        "chunking_mode": chunking_mode,
        "preprocessing_stats": {
            "table_tasks_generated": len(table_tasks),
            "hard_recall_count": self.diagnostics.get("hard_recall_count", 0),
            "hard_recall_sentence_ids": self.diagnostics.get("hard_recall_sentence_ids", []),
            "hard_recall_block_ids": self.diagnostics.get("hard_recall_block_ids", []),
            "hard_recall_kid_ids": self.diagnostics.get("hard_recall_kid_ids", []),
            "hard_recall_patterns_hit": self.diagnostics.get("hard_recall_patterns_hit", {}),
            "hard_recall_context_expanded_count": self.diagnostics.get("hard_recall_context_expanded_count", 0),
            "hard_recall_overflow": self.diagnostics.get("hard_recall_overflow", 0),
            "kinetics_signal_count": kinetics_signal_count,
            "material_signal_count": material_signal_count,
            "caption_sentence_count": caption_count,
            "signal_type_distribution": dict(sorted(
                (st, sum(1 for s in self.sentences if s.signal_type == st))
                for st in sorted(set(s.signal_type for s in self.sentences if s.signal_type))
            )),
            # ---- 新增诊断字段 ----
            "text_normalization": {
                "removed_global_lowercase_join_rule": True,
                "formula_fixes_enabled": True,
                "ligature_fixes_enabled": True,
            },
            "table_extraction": {
                "total_tables_detected": (getattr(self, "_table_extraction_task", {}) or {}).get("stats", {}).get("total_detected", len(table_tasks)),
                "total_tables_selected": (getattr(self, "_table_extraction_task", {}) or {}).get("stats", {}).get("total_selected", len(table_tasks)),
                "high_priority_tables": (getattr(self, "_table_extraction_task", {}) or {}).get("stats", {}).get("high_priority", 0),
                "medium_priority_tables": (getattr(self, "_table_extraction_task", {}) or {}).get("stats", {}).get("medium_priority", 0),
                "low_priority_tables": (getattr(self, "_table_extraction_task", {}) or {}).get("stats", {}).get("low_priority", 0),
                "table_types_count": (getattr(self, "_table_extraction_task", {}) or {}).get("stats", {}).get("table_types_count", {}),
                "needs_vlm_fallback_count": (getattr(self, "_table_extraction_task", {}) or {}).get("stats", {}).get("needs_vlm_fallback_count", 0),
                "tables_included_count": len((getattr(self, "_table_extraction_task", {}) or {}).get("tables", [])),
            },
            "output": {
                "llm_chunks_count": len(self.chunks) if hasattr(self, "chunks") else 0,
                "vlm_tasks_count": len(vlm_tasks),
                "table_tasks_count": len(table_tasks),
            },
        },
    }

        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(mid_json, f, indent=2, ensure_ascii=False)
        return mid_json

    def _build_prompt_template(self) -> str:
        enzyme_enum = get_enzyme_type_enum_string()

        doc_hints = ""
        if self.document_kind == "supplementary":
            doc_hints = (
                "\n\nDOCUMENT CONTEXT: This is a Supplementary Information / Supporting Information document. "
                "It contains additional experimental details, characterization data, and supplementary tables/figures. "
                "Focus on extracting: (1) supplementary kinetic parameters and assay conditions, "
                "(2) additional characterization of the main nanozyme system, "
                "(3) control experiments and comparison data. "
                "Clearly distinguish the main nanozyme system (role=protagonist) from comparator/benchmark systems."
            )
        elif self.document_kind == "review":
            doc_hints = (
                "\n\nDOCUMENT CONTEXT: This is a review article. "
                "It likely discusses MULTIPLE nanozyme systems from different studies. "
                "Extract each distinct nanozyme system as a separate entry. "
                "Assign role='protagonist' to the main systems discussed, "
                "role='comparator' to systems used for comparison, "
                "role='cited' to systems merely referenced."
            )
        elif self.document_kind == "communication":
            doc_hints = (
                "\n\nDOCUMENT CONTEXT: This is a short communication/letter. "
                "It may have condensed experimental sections and combined results/discussion. "
                "Do not assume complete experimental datasets are available."
            )

        detected_enzyme_types = set()
        for sent in self.sentences if hasattr(self, 'sentences') else []:
            tags = getattr(sent, 'value_tags', [])
            if 'activity' not in tags:
                continue
            text_lower = sent.text.lower() if hasattr(sent, 'text') else ""
            for _etype, _meta in ENZYME_REGISTRY.items():
                if _meta["keywords"][0] in text_lower:
                    detected_enzyme_types.add(EnzymeType.normalize_canonical(_etype.value))
        if len(detected_enzyme_types) >= 2:
            doc_hints += (
                "\n\nIMPORTANT: This paper discusses MULTIPLE enzyme-like activities "
                f"(detected: {', '.join(sorted(detected_enzyme_types))}). "
                "For each activity, clearly specify the substrate, optimal conditions, and kinetic parameters. "
                "Do not mix substrates or conditions across different activity types."
            )

        return f"""你是纳米酶文献信息抽取专家。

你将看到一段经过预处理的论文文本。输入中每个句子都带有 sentence_id，例如：
[S0001|p6|results] ...
[S0002|p6|results] ...

重要说明：
1. 当前文本块中可能包含多个纳米酶 system（多个材料体系）
2. 同一个 system 可能包含多个 enzyme-like activity
3. 同一个 substrate 在不同 assay_type 下可能有不同的 Km/Vmax
4. 优先依据完整正文句子和 figure caption
5. 图内零碎 OCR 文本、坐标轴刻度、单位残片只能作为补充，不可单独驱动关键结论
6. 缺失值用 null，不要臆测补全
7. 只能输出一个 JSON 对象
8. 不要输出 Markdown，不要输出解释，不要输出注释

CRITICAL DISTINCTION:
Do NOT confuse the catalytic substrate (e.g., TMB, ABTS, AR, H2O2) with the sensing target / analyte (e.g., Cys, Cu2+, glucose, cancer cells).
Analytes MUST NEVER be placed in the substrates list.
They should only appear in key_findings, application, or other clearly non-substrate fields.

你的任务：
从当前文本块中提取“所有明确出现的”：
- paper 级信息
- nanozyme systems
- catalytic activities
- assays
- kinetics
- mechanism hypotheses
- key findings
- evidence refs

输出 JSON schema：

{{
  "schema_version": "nanozyme.v1",
  "paper": {{
    "title": null,
    "doi": null,
    "year": null
  }},
  "nanozyme_systems": [
    {{
      "system_local_id": "sys_1",
      "material_name_raw": null,
      "material_name_normalized": null,
      "morphology": null,
      "metal_centers": [],
      "coordination_environment": null,
      "defects": [],
      "characterization_methods": [],
      "synthesis_method": null,
      "size_info": null,
      "surface_modification": [],
      "stability_info": {{}},
      "evidence_refs": [],
      "role": "protagonist"
    }}
  ],
  "catalytic_activities": [
    {{
      "activity_local_id": "act_1",
      "system_local_id": "sys_1",
      "enzyme_like_type": null,
      "assay_context": null,
      "substrates": [],
      "assays": [
        {{
          "assay_local_id": "assay_1",
          "assay_type": null,
          "signal_type": null,
          "buffer": null,
          "pH": null,
          "temperature_c": null,
          "time_window_s": null,
          "evidence_refs": []
        }}
      ],
      "kinetics": [
        {{
          "assay_local_id": "assay_1",
          "parameter": "Km",
          "value": null,
          "unit": "mM",
          "target_substrate": null,
          "evidence_refs": []
        }},
        {{
          "assay_local_id": "assay_1",
          "parameter": "Vmax",
          "value": null,
          "unit": null,
          "target_substrate": null,
          "evidence_refs": []
        }}
      ],
      "optimal_conditions": {{
        "optimal_pH": null,
        "optimal_temperature_c": null
      }},
      "key_findings": [],
      "mechanism_hypotheses": [],
      "selectivity": null,
      "applications": [
        {{
          "application_local_id": "app_1",
          "system_local_id": "sys_1",
          "activity_local_id": "act_1",
          "application_type": null,
          "application_description": null,
          "target_analyte": null,
          "detection_limit": null,
          "linear_range": null,
          "sensitivity": null,
          "selectivity_notes": null,
          "biocompatibility_notes": null,
          "performance_comparison": null,
          "evidence_refs": []
        }}
      ],
      "evidence_refs": []
    }}
  ],
  "evidence": [
    {{
      "sentence_id": null,
      "page": null,
      "section": null,
      "text_quote": null,
      "source_kind": "text"
    }}
  ],
  "applications": [
    {{
      "application_local_id": "app_top_1",
      "system_local_id": "sys_1",
      "activity_local_id": null,
      "application_type": null,
      "application_description": null,
      "target_analyte": null,
      "detection_limit": null,
      "linear_range": null,
      "sensitivity": null,
      "selectivity_notes": null,
      "biocompatibility_notes": null,
      "performance_comparison": null,
      "evidence_refs": []
    }}
  ]
}}

规范化要求：
- enzyme_like_type 只能使用以下枚举之一：
  {enzyme_enum}

- assay_type 只能使用以下枚举之一：
  {get_assay_type_enum_string()}

- application_type 只能使用以下枚举之一：
  {get_application_type_enum_string()}

- 科学计数法统一使用 e 格式，例如：
  33×10^-8 -> 3.3e-7

- For each nanozyme_system, assign a "role" field:
  - "protagonist": The nanozyme system that this paper synthesizes, characterizes, and primarily studies. Usually only 1-2 per paper.
  - "comparator": Known materials or enzymes used as benchmarks/controls for comparison (e.g., natural enzymes, commercial nanomaterials used as positive controls).
  - "cited": Systems only mentioned in the introduction or references as prior work, not experimentally studied in this paper.
  Default to "protagonist" only when the system has direct experimental evidence (synthesis, characterization, or activity measurement) in this paper.

- For each enzyme_like_activity, assign an "assay_context" field:
  - "positive": The activity is confirmed present through experimental evidence (e.g., "exhibited excellent peroxidase-like activity", "showed high catalytic activity").
  - "negative": The activity is explicitly stated as absent or negligible (e.g., "no significant peroxidase-like activity was observed", "failed to catalyze").
  - "control": The assay was performed as a control/reference experiment to validate specificity, not as the main finding (e.g., "to rule out peroxidase-like activity, TMB oxidation was tested", "determination of peroxidase-like activity" when the paper's main focus is a different activity).
  IMPORTANT: When a paper focuses on one specific enzyme-like activity (e.g., catechol oxidase-like), and other activities are tested only to demonstrate specificity or rule them out, those other activities MUST be marked as "control" or "negative", NOT "positive". An assay performed does NOT mean the activity is positive — only mark "positive" when the paper explicitly confirms the activity is present and significant.
  Default to "positive" ONLY when the text clearly confirms the activity is present and significant.

- substrates must list only true catalytic reactants used in the catalytic assay. Never put sensing targets / analytes into substrates, even if they modulate signal or are the detection target.

- applications 提取指引：
  - 每个应用必须关联到一个 nanozyme_system（通过 system_local_id）和/或一个 catalytic_activity（通过 activity_local_id）
  - application_type 必须使用上述枚举值
  - target_analyte 是应用的目标检测物或作用对象（如 glucose, H2O2, cancer cells），不是催化底物
  - detection_limit / linear_range / sensitivity 仅在论文明确给出数值时填写，否则为 null
  - 如果一个应用同时利用多个催化活性（如级联反应），放在顶层 applications 列表中，activity_local_id 可为 null
  - 如果应用只利用单一催化活性，嵌套在该 catalytic_activity 的 applications 列表中
  - biocompatibility_notes 仅在论文明确讨论生物相容性/细胞毒性时填写
  - performance_comparison 仅在论文明确对比天然酶或其他纳米酶时填写
- selectivity 描述该催化活性的选择性特征（如"对 TMB 有高选择性，对 ABTS 无催化活性"）
- synthesis_method 描述纳米酶的合成方法（如 hydrothermal, coprecipitation, sol-gel, pyrolysis）
- size_info 描述纳米酶的尺寸信息（如 "50 nm", "10-20 nm diameter"）
- surface_modification 列出表面修饰（如 ["PEGylation", "chitosan coating"]）
- stability_info 描述稳定性信息，使用字典格式，可包含 pH_range, temp_range, storage, reusability_cycles 等 key
- 如果一个 chunk 中出现多个系统（例如：同时出现母体/对照体系 MnCo2O4 和目标/改性体系 R-MnCo2O4），**必须严格拆成多个** nanozyme_systems，绝不能合并。
- 如果同一 system 有多个 assay（例如 UV-vis kinetics 和 SERS-kinetics），必须分别记录
- kinetics 中的 parameter (如 Km/Vmax) 必须有明确的数值才生成，如果文中未给出明确数值，请勿生成该 kinetic 记录（**绝不生成 value 为 null 的 kinetics 对象**）。
- 不同 assay 下的 Km/Vmax 不能合并
- evidence_refs 只能引用输入中真实存在的 sentence_id。要求：**只引用给出定义、数值或核心特征的那 1-2 句最直接相关的句子**，不要盲目挂载大量外围表征句。
- evidence.page 必须是整数，例如 1，不要输出 p1 或 "1"（带引号）
- 如果无法确定 material_name_normalized，就保留 material_name_raw 并将 normalized 设为 null
- mechanism_hypotheses 应尽量简短，不要复述整段正文
{doc_hints}

现在处理以下文本：

--- chunk start ---
{{text}}
--- chunk end ---
"""
