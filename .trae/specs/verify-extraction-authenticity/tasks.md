# Tasks

- [x] Task 1: 实现 ExtractionVerifier 核心类 — 新建 extraction_verifier.py，包含数值回查、文本回查、错配检测、验证报告生成
  - [x] SubTask 1.1: 实现 _find_numeric_in_source 方法 — 在原文 text_chunks 中搜索数值（支持科学计数法归一化匹配）
  - [x] SubTask 1.2: 实现 _find_text_in_source 方法 — 在原文中搜索文本型字段值（如 enzyme_like_type、synthesis_method）
  - [x] SubTask 1.3: 实现 _detect_cross_context_mismatch 方法 — 检测不同字段的 evidence_text 是否指向不同材料/条件
  - [x] SubTask 1.4: 实现 verify_record 方法 — 对整条记录执行全字段验证，生成 verification 报告
  - [x] SubTask 1.5: 实现 _compute_verification_rate 方法 — 计算整体验证率并调整 confidence

- [x] Task 2: 证据锚定机制 — 修改 single_main_nanozyme_extractor.py，确保每个提取字段绑定 evidence_text
  - [x] SubTask 2.1: 规则提取阶段 — _extract_kinetics_from_text / _extract_kinetics_from_table 写入字段时同时写入 evidence_text
  - [x] SubTask 2.2: LLM 合并阶段 — _merge_llm 中 LLM 值补充时检查 evidence_text 是否存在，不存在则标记 llm_no_evidence
  - [x] SubTask 2.3: VLM 合并阶段 — _merge_vlm 中 VLM 值补充时检查 evidence_text / caption 是否存在
  - [x] SubTask 2.4: 应用提取阶段 — application 字段写入时附带 evidence_text

- [x] Task 3: LLM/VLM 反幻觉验证集成 — 在提取流水线中集成 ExtractionVerifier
  - [x] SubTask 3.1: 在 SingleMainNanozymePipeline.extract() 中，合并 LLM 结果后调用 ExtractionVerifier.verify_llm_results()
  - [x] SubTask 3.2: 在合并 VLM 结果后调用 ExtractionVerifier.verify_vlm_results()
  - [x] SubTask 3.3: hallucination_suspect 的数值降级处理 — 从 kinetics 移入 important_values，原字段设为 None
  - [x] SubTask 3.4: vlm_unverified 的数值保留但标记 needs_review=True, confidence="low"

- [x] Task 4: 信息错配检测集成 — 在 ConsistencyGuard 中增加跨上下文错配检测
  - [x] SubTask 4.1: 检测 kinetics 内部字段（Km/Vmax/kcat）的 evidence_text 是否指向不同材料
  - [x] SubTask 4.2: 检测 kinetics 与 conditions 的 evidence_text 是否指向不同实验条件
  - [x] SubTask 4.3: 检测 application 与 enzyme_like_type 的 evidence_text 是否矛盾
  - [x] SubTask 4.4: 错配结果写入 diagnostics.verification.mismatches

- [x] Task 5: 验证报告与 diagnostics 集成 — 修改 DiagnosticsBuilder，增加 verification 子结构
  - [x] SubTask 5.1: DiagnosticsBuilder 增加 set_verification() 方法和 _verification 字段
  - [x] SubTask 5.2: build() 方法中合并 verification 信息到输出
  - [x] SubTask 5.3: WARNING_ENUMS 增加 hallucination_suspect、vlm_unverified、cross_material_mismatch、condition_mismatch、activity_application_mismatch、llm_no_evidence
  - [x] SubTask 5.4: verification_rate 影响 confidence 的逻辑实现

- [x] Task 6: 端到端验证 — 用真实文献测试验证系统效果
  - [x] SubTask 6.1: 选取3篇已知文献，人工标注关键字段的真实值和原文位置
  - [x] SubTask 6.2: 运行提取流程，检查 verification 报告是否正确标记 hallucination_suspect
  - [x] SubTask 6.3: 检查验证率计算是否准确
  - [x] SubTask 6.4: 更新迭代记录

# Task Dependencies
- [Task 2] depends on [Task 1] (证据锚定是验证的前提)
- [Task 3] depends on [Task 1, Task 2] (反幻觉验证需要 ExtractionVerifier 和证据锚定)
- [Task 4] depends on [Task 1] (错配检测需要 ExtractionVerifier)
- [Task 5] depends on [Task 1] (验证报告需要 ExtractionVerifier 输出)
- [Task 6] depends on [Task 1, Task 2, Task 3, Task 4, Task 5]
- [Task 2, Task 4, Task 5] 可在 Task 1 完成后并行
