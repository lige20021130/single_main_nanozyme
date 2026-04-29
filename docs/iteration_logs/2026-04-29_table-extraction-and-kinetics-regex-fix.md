# 表格提取与动力学正则修复

## 更新时间
2026-04-29 13:25

## 更新类型
- Bug 修复 / 功能开发

## 背景
基于10篇真实文献验证结果，发现表格提取和动力学参数正则匹配存在多个严重bug：
1. `_LOD_PATTERN` / `_LINEAR_RANGE_PATTERN` 命名bug导致 `get_sensing_values()` 运行时 NameError
2. 表格分类系统不一致（预处理器 vs 提取器使用不同类型名和字段名）
3. PDF解析器无法提取表格单元格文本（rows为空），导致表格数据完全丢失
4. `_KCAT_PATTERNS` 误匹配 "kcat/Km" 中的 "kcat"，导致错误提取
5. `_KCAT_KM_PATTERNS` 字符类 `[\u207b⁻\-–]` 在 Python 中有冲突，导致无法匹配
6. `_KM_PATTERNS` 不支持 "Km values to TMB and H2O2 are 0.067 and 0.048 mM" 多底物格式

## 改动内容

### 1. 修复 _LOD_PATTERN / _LINEAR_RANGE_PATTERN 命名bug (L1925-1938)
- 改为使用 `_LOD_PATTERNS` 和 `_LINEAR_RANGE_PATTERNS`（复数形式）
- 使用循环匹配替代单次匹配

### 2. 修复 classify_and_summarize 字段兼容性 (L1857-1903)
- 同时支持 `headers` 和 `columns` 字段
- 保留 `content_text`、`markdown`、`caption` 等文本字段
- kinetics_table 也添加 `this_work_rows` 过滤

### 3. 增强 get_kinetics_values 支持空rows回退 (L1905-1978)
- 当 `rows` 为空时，从 `content_text` 和 `markdown` 中提取动力学数据
- 提取 `_extract_kinetics_from_row` 为独立方法，复用正则匹配逻辑
- 支持按材料名和 "this work" 关键词过滤行

### 4. 修复 _KCAT_PATTERNS 误匹配 kcat/Km (L296-310)
- 所有 `_KCAT_PATTERNS` 添加 `(?!\s*/\s*Km)` 负向前瞻
- 防止 "kcat/Km" 中的 "kcat" 被错误匹配为独立 kcat 值

### 5. 修复 _KCAT_KM_PATTERNS 字符类bug (L317-325)
- 将 `[\u207b⁻\-–\u2212\u2013]` 替换为 `(?:\u207b|\u2212|\u2013|-)`
- 解决 Python 正则字符类中 `⁻` 和 `\-` 的冲突问题
- 增加前缀匹配长度 `{0,40}?` 以支持更长的材料名
- 添加 `\s` 到单位分隔符以支持空格分隔

### 6. 修复 _KM_PATTERNS 多底物格式 (L281)
- 将 `\w[\w\d\-]*` 替换为 `\S+` 以支持 H2O2 等含数字底物名
- 修改为匹配 "0.067 and 0.048 mM" 格式（数字间有 "and"）

### 7. 增强 _normalize_ocr_scientific 科学记数法 (L343-344)
- 添加 `[\^]?` 支持以处理 `10^-8` 格式中的 `^` 符号

## 验证结果

### 修复前（纯规则提取）
| 字段 | 填充率 |
|------|--------|
| Km | 1/8 (12%) |
| Vmax | 0/8 (0%) |
| kcat | 1/8 (12%) — 错误值 |
| kcat_Km | 0/8 (0%) |
| LOD | 2/8 (25%) |

### 修复后（纯规则提取）
| 字段 | 填充率 |
|------|--------|
| Km | 2/8 (25%) — +13% |
| Vmax | 0/8 (0%) |
| kcat | 0/8 (0%) — 修复了错误值 |
| kcat_Km | 1/8 (12%) — +12% |
| LOD | 3/8 (38%) — +13% |

### 关键改进
- **MoS2@CoFe2O4**: Km=0.067 mM (TMB) ✅ — 之前为 None
- **OV-Mn3O4**: kcat_Km=1.88e-08 ✅ — 之前为 None
- **Breaking_t_0534ddd5**: sensing_table=1 ✅ — 表格分类修复生效
- **kcat 错误修复**: OV-Mn3O4 的 kcat 不再被错误提取为 8.0

## 未改动内容
- 预处理流程（nanozyme_preprocessor_midjson.py）
- VLM提取逻辑（vlm_extractor.py）
- 数值验证逻辑（numeric_validator.py）
- LLM提取逻辑（llm_extractor.py）

## 风险与后续
- Vmax=0% 仍是根本限制（数据在ESM中）
- PDF解析器无法提取表格单元格文本，需要考虑 VLM 表格识别方案
- 当前 kinetics 结构只支持一组 Km/Vmax，多底物文献只能提取第一个底物的值
- `_KCAT_PATTERNS` 的负向前瞻 `(?!\s*/\s*Km)` 可能影响极少数合法的 "kcat / Km" 写法
