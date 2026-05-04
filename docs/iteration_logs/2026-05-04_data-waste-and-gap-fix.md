# 数据浪费与理论-现实脱节修复

## 更新时间
2026-05-04 23:30

## 更新类型
- Bug 修复 / 功能开发

## 背景
全面审查系统数据浪费和理论-现实脱节问题，发现：
1. CrossValidationAgent 访问 VLM 字段路径错误，VLM 交叉验证完全失效
2. _merge_vlm 未合并 VLM 提取的 kcat/kcat_Km
3. TableExtractor 的 assay_condition（pH/temperature/buffer）完全未使用
4. chunk_contexts 的 section_type/signal_types 完全未使用，_infer_section 重新用关键词推断
5. extracted_hints 的 detected_enzyme_types 等字段完全未使用
6. table_sensing_values 只在 applications 为空时使用，已有 sensing 应用时 LOD/linear_range 被丢弃

## 改动内容

### cross_validation_agent.py
- **修复 VLM 字段路径**：从 `vlm_r.get("kinetics", {})` 改为 `vlm_r.get("extracted_values", {})`，正确解析嵌套结构
- **修复 particle_size/sensing_performance/other_values 路径**：从 `vlm_r.get(...)` 改为 `ev.get(...)`
- VLM 交叉验证现在能正确读取 kinetics、particle_size、sensing_performance、other_values

### single_main_nanozyme_extractor.py
- **_merge_vlm 新增 kcat/kcat_Km 合并**：VLM 提取的 kcat 和 kcat_Km 现在会填充到 kinetics 和 important_values
- **TableExtractor assay_condition 整合**：从 LLM 表格提取结果中读取 pH、temperature、buffer，回填到 main_activity.conditions
- **_infer_section 利用 chunk_contexts**：优先使用预处理器已计算的 section_type 和 signal_types，回退到关键词匹配
- **detected_enzyme_types 优先使用**：enzyme_like_type 提取时优先使用预处理器已检测的酶类型，避免重复全文扫描
- **table_sensing_values 补充模式**：不再只在 applications 为空时使用，改为匹配已有 sensing 应用并补充 LOD/linear_range

## 未改动内容
- DiagnosticsBuilder 两套实现未统一（影响范围大，需单独迭代）
- ConsistencyAgent 只 warning 不自动修正（需设计修正策略）
- _extract_kinetics_from_flattened_table 与 _extract_kinetics_from_text 重叠未清理
- SingleRecordAssembler 废弃代码未删除
- sentence_metadata、preprocessing_stats 等诊断数据未使用（设计如此）

## 验证方式
- py_compile.compile() 两个文件均通过
- 运行时 import 验证通过

## 风险与后续
- _infer_section 使用 chunk_contexts 后，section 分类结果可能与之前不同，需观察
- CrossValidationAgent 的 VLM 交叉验证现在能正确工作，可能改变 kinetics 值的选择
- 后续应统一 DiagnosticsBuilder、清理废弃代码、设计 ConsistencyAgent 自动修正策略
