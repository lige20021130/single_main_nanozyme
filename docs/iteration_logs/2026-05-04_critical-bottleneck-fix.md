# 关键瓶颈修复：表格VLM fallback、动力学专用prompt、名称清洗、morphology过滤

## 更新时间
2026-05-04 03:30

## 更新类型
- Bug 修复 / 功能开发

## 背景
四轮优化后全链路测评发现系统存在4个关键瓶颈：
1. 表格VLM fallback任务未被消费（代码断裂）— 预处理器生成了vlm_fallback_tasks但_call_vlm未处理
2. VLM prompt过于宽泛 — 缺少针对动力学/表格的专用prompt
3. 材料名称混入底物/系统词 — 如"Fe-N-C/H2O2 system"
4. Morphology字段被VLM图片描述污染 — 如Mo-SAN论文

## 改动内容

### 1. 修复表格VLM fallback代码断裂
- **文件**: `single_main_nanozyme_extractor.py`
- 新增 `_call_table_vlm_fallback()` 方法（约75行），消费预处理器生成的`vlm_fallback_tasks`
- 修改 `extract()` 方法中VLM合并逻辑，将表格VLM结果与图片VLM结果合并后统一处理
- 表格VLM任务使用`VLMExtractor._extract_from_image()`，传入`elem_type="table"`和`caption_type="kinetics_caption"`

### 2. 增加动力学专用VLM prompt
- **文件**: `vlm_extractor.py`
- 新增 `TABLE_VLM_PROMPT` 常量（约60行），专门用于表格截图的数值提取
- prompt特点：强调读取Km/Vmax/kcat/kcat_Km、区分"this work"行、科学计数法完整提取
- 修改 `_extract_from_image()` 方法，根据`elem_type`和`vlm_reason`自动选择TABLE_VLM_PROMPT或VISION_PROMPT

### 3. 材料名称清洗
- **文件**: `single_main_nanozyme_extractor.py`
- 在 `validate_schema()` 中新增名称清洗逻辑（约22行）
- 去除底物后缀：`/H2O2`、`/TMB`、`/ABTS`等
- 去除系统词后缀：`system`、`solution`、`mixture`、`catalyst`等
- 清洗时记录warning（如`name_cleaned_substrate_removed`）
- 测试验证：`Fe-N-C/H2O2 system` → `Fe-N-C` ✅

### 4. Morphology字段VLM输出过滤
- **文件**: `single_main_nanozyme_extractor.py`
- 在 `_merge_vlm()` 的observations合并处增强过滤
- 新增 `_MORPH_FIGURE_DESC_RE` 正则：匹配diagram/schematic/pathway/mechanism/catalyzes等非形貌词
- 新增 `_MORPH_VALID_TERMS` 正则：只保留包含形貌词汇（nanoparticle/nanosheet/sphere等）的观察
- 移除fallback到`obs_text[:60]`的逻辑，过滤后为空则不填入morphology

## 未改动内容
- 规则提取逻辑（KineticsAgent等）未改动
- LLM提取和合并逻辑未改动
- 预处理器逻辑未改动
- ExtractionVerifier/ConsistencyGuard未改动

## 验证方式
- 代码导入验证：`from single_main_nanozyme_extractor import ...` ✅
- 名称清洗单元测试：12个测试用例全部通过 ✅
- VLM模块导入验证：`from vlm_extractor import TABLE_VLM_PROMPT` ✅
- 全链路测评：10篇PDF提取，8篇成功，名称清洗生效（Fe-N-C/H2O2 system → Fe-N-C）

## 风险与后续
- 表格VLM fallback依赖表格有image_path，部分PDF解析可能不提供表格截图
- 名称清洗可能误删合法后缀（如"Co-Fe LDHs@Au@MA"中的@MA不是底物）
- Morphology过滤可能过于严格，导致某些合法观察被丢弃
- 下一步：验证表格VLM fallback在实际论文中的效果，可能需要调整表格图片筛选策略
