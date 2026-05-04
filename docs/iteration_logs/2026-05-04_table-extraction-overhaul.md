# 表格提取系统重大修复

## 更新时间
2026-05-04 22:00

## 更新类型
- Bug 修复 / 功能开发 / 架构调整

## 背景
审查发现当前系统对文献表格信息的处理存在严重问题：
1. `TableExtractor`（LLM 结构化表格提取器）已开发但完全未接入管道
2. 结构化 rows/cells 被展平为文本再用正则匹配，行列对应关系丢失
3. 三套不一致的表格分类系统，预处理器分类结果被丢弃
4. general_table 和 characterization_table 数据完全浪费
5. 表格标题关联仅靠页码距离，大量表格无标题
6. 代码审查发现 _find_table_captions 和 _associate_table_caption 是死代码

## 改动内容

### nanozyme_preprocessor_midjson.py
- **新增模块级常量 `_TABLE_NUM_PAT`**：Table 编号匹配正则，优先匹配 `[A-Z]\d*`，避免 "Table A1" 被截断为 "1"
- **重写 `_find_table_captions()`**：捕获标题行后续段落作为完整标题（多行标题），非字典元素 continue 而非 break
- **重写 `_associate_table_caption()`**：优先 Table 编号匹配，回退页码距离（阈值从 2 页放宽到 3 页）
- **在 `_build_table_extraction_task()` 中调用标题关联**：修复死代码问题，让标题关联真正生效

### single_main_nanozyme_extractor.py
- **新增 `_PREPROCESSOR_TO_SMN_TYPE` 映射**：统一预处理器和 SMN 的分类系统，尊重预处理器分类结果
- **重写 `TableProcessor.classify_and_summarize()`**：优先使用预处理器分类，first-match-wins 改为映射优先，general_table 不再丢弃数据
- **新增 `_find_column_indices()`**：基于列名关键词匹配列索引的通用方法
- **新增 `_extract_kinetics_from_structured_rows()`**：利用 rows/cells 的列名结构提取 Km/Vmax/kcat/kcat_Km，保留行列对应关系
- **改进 `get_kinetics_values()`**：优先结构化提取，回退正则提取，同时处理 general_tables
- **改进 `get_sensing_values()`**：新增结构化列名提取 LOD 和 linear_range，同时处理 general_tables
- **新增 `get_characterization_values()`**：从 characterization 表格提取 BET 表面面积、孔径、粒径、zeta potential
- **接入 `TableExtractor`（LLM 表格提取）**：在 extract() 中调用 llm_extractor.TableExtractor，将 LLM 结果整合到 table_kinetics_values
- **改进 `_extract_kinetics_from_table()`**：支持 table_structured 和 table_llm 来源，使用 _parse_scientific_notation 处理科学计数法
- **将 characterization 数据写入 record**：surface_area、pore_size、particle_size、zeta_potential 写入 selected_nanozyme
- **扩展 characterization_table 正则**：新增 FTIR/Raman/UV-vis/XRF/ICP/EDS/TGA/DLS/XAS
- **修复 application_performance 映射**：从 sensing_table 改为 general_table
- **修复 particle_size 类型不一致**：用正则提取数字部分再转 float

## 未改动内容
- llm_extractor.py 中 TableExtractor 的 prompt 和 schema 未修改（仅接入调用）
- table_classifier.py 旧管道代码未修改
- vlm_extractor.py 未修改
- diagnostics_builder.py 未修改
- 表格配额截断逻辑未修改
- VLM 回退触发条件未修改

## 验证方式
- `py_compile.compile()` 两个文件均通过
- `from single_main_nanozyme_extractor import TableProcessor` 成功
- `_TABLE_NUM_PAT` 正则测试：Table 1→1, Table S1→S1, Table A1→A1
- TableProcessor 实例化成功，新方法 _find_column_indices/_extract_kinetics_from_structured_rows/get_characterization_values 均存在

## 风险与后续
- TableExtractor 的 LLM 调用可能增加延迟，需监控实际耗时
- characterization 提取的关键词映射可能需要根据实际表格格式微调
- 后续可扩展 TableExtractor 的 prompt 支持 characterization 和 sensing 字段
- 后续可改进 VLM 回退触发条件（增加 OCR 质量评估）
