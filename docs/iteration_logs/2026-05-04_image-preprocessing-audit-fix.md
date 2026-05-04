# 图片预处理丢失审查与修复

## 更新时间
2026-05-04 10:50

## 更新类型
- Bug 修复 / 功能优化 / 新增功能

## 背景
对2021.6.1文件夹中105篇纳米酶文献PDF进行图片预处理审查，发现系统解析和预处理存在图片丢失问题。总体存活率仅48.6%，9篇文献100%图片丢失（72张有价值图片），44张≥100×100尺寸的图片因无caption被误过滤。

## 改动内容

### 1. 修复 WinError 206 路径过长导致预处理崩溃
- **文件**: `nanozyme_preprocessor_midjson.py:333-338`
- **问题**: 当PDF文件名过长时，`high_value_dir`路径超过Windows 260字符限制，导致`mkdir`失败
- **修复**: `pdf_stem`超过80字符时自动截断为`年份_MD5哈希前8位`格式
- **影响**: 修复了3篇预处理崩溃文献中的2篇

### 2. 降低 uncaptioned_min_both 阈值
- **文件**: `nanozyme_preprocessor_midjson.py:159`
- **改动**: `uncaptioned_min_both` 从 200 降至 150
- **效果**: 尺寸在150-200之间的无caption图片不再被强制过滤

### 3. 增强 caption 检测支持 Table 格式
- **文件**: `nanozyme_preprocessor_midjson.py:176-178, 4403, 4424-4427, 4446`
- **改动**: `caption_patterns` 新增 `"table"` 类别，`_parse_caption_label` 和 fallback 均加入 Table 支持
- **效果**: Table 1/Table 2等表格标题被识别为caption

### 4. 新增 PyMuPDF Fallback 机制（核心改动）
- **文件**: `pdf_basic_gui.py:1034-1110`
- **阶段C2**: 当 `opendataloader_pdf` 完全失败（API+CLI均无法生成JSON）时，用 PyMuPDF 提取图片和文本，生成最小JSON
- **阶段D0**: 当JSON存在但图片目录缺失时，用 PyMuPDF 补提取图片文件
- **路径安全**: PyMuPDF fallback 中使用截断 stem（>80字符时自动截断为`年份_哈希`），避免 Windows 路径超限
- **效果**: 9篇失败文献全部修复，PyMuPDF提取73张图片，预处理后存活66张，存活率90.4%

## 失败文献审查详情

### 6篇解析完全失败（opendataloader_pdf 无法生成JSON）
| 文献 | 原因 | PyMuPDF提取 | 预处理存活 |
|---|---|---|---|
| 2022-AC-Efficient Biocatalytic... | 文件名含`−`(U+2212) | 9 | 8 |
| 2023-Highly-oxidizing Au@MnO2... | 文件名含`−`(U+2212) | 12 | 8 |
| Aptamer-Modified Cu2+... | 文件名含`‑`(U+2011) | 6 | 6 |
| Isolated Cobalt Atoms... | 文件名含`‑`(U+2011) | 8 | 8 |
| Rational Design of N‑Doped... | 文件名含`‑`(U+2011) | 8 | 8 |
| Self-cascade MoS2... | 文件名含`†`(U+2020) | 7 | 6 |

### 3篇图片文件未提取（JSON存在但图片目录缺失）
| 文献 | PyMuPDF提取 | 预处理存活 |
|---|---|---|
| 2022-talanta-Colorimetric... | 7 | 7 |
| 2023-In-situ growth of SrTiO3... | 7 | 7 |
| 2023-JACS-Dual Active Centers... | 9 | 8 |

## 验证方式
- 对9篇失败文献运行PyMuPDF fallback测试，全部成功
- PyMuPDF提取73张图片，预处理后存活66张，存活率90.4%
- 对105篇文献运行回归测试，99篇预处理成功，0篇报错
- 总存活图片565张，平均caption匹配率0.746
- git push成功

## 未改动内容
- `opendataloader_pdf` 解析器本身未改动
- `max_images_main`/`max_images_supplementary` 截断限制未调整
- VLM阶段的二次过滤逻辑未改动

## 风险与后续
- PyMuPDF fallback 生成的JSON结构较简单（只有text和image元素），缺少opendataloader_pdf的完整结构化信息（段落、标题层级等），预处理阶段的文本分析可能不够精细
- 降低阈值可能让少量非科学图片进入vlm_tasks，但影响有限
