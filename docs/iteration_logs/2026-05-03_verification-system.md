# 纳米酶文献提取信息真实性验证系统

## 更新时间
2026-05-03 22:00

## 更新类型
- 功能开发

## 背景
当前系统存在严重的信息真实性盲区：LLM/VLM 提取结果可能包含大模型捏造的数值、模糊推断的结论、以及跨材料/跨上下文的信息错配。现有验证机制（NumericValidator、ConsistencyGuard、CrossValidationAgent）仅关注数值量级合理性和归属判断，无法验证提取值是否真正存在于原文中。需要一个专门的验证层，确保每条提取信息都可溯源到原文具体位置，杜绝大模型幻觉和模糊处理。

## 改动内容

### 新增文件
- `extraction_verifier.py` — 核心验证类 ExtractionVerifier
  - `_find_numeric_in_source()` — 在原文中搜索数值（支持科学计数法归一化匹配，如 1.5×10⁻¹ 匹配 0.15）
  - `_find_text_in_source()` — 在原文中搜索文本型字段值（enzyme_like_type、synthesis_method 等，支持关键词映射）
  - `_detect_cross_context_mismatch()` — 检测不同字段的 evidence_text 指向不同材料/条件
  - `verify_record()` — 对整条记录执行全字段验证，生成 verification 报告
  - `verify_llm_results()` — 专门验证 LLM 提取结果
  - `verify_vlm_results()` — 专门验证 VLM 提取结果
  - `demote_hallucinated_kinetics()` — 将 hallucination_suspect 的数值从 kinetics 降级到 important_values
  - `_compute_verification_rate()` — 计算整体验证率并调整 confidence

### 修改文件
- `single_main_nanozyme_extractor.py`
  - EMPTY_RECORD 模板增加 `_evidence_Km/Vmax/kcat/kcat_Km` 字段
  - 规则提取阶段所有 kinetics 写入点增加 evidence 锚定
  - `_merge_llm` 中 LLM 值补充时检查 evidence_text，缺失标记 `_llm_no_evidence`
  - `_merge_vlm` 中 VLM 值补充时检查 caption，缺失标记 `_vlm_no_evidence`
  - 应用提取阶段 application 字段附带 `_evidence`
  - DiagnosticsBuilder 增加 `__init__`、`set_verification()` 方法和 verification_rate 影响 confidence 逻辑
  - SingleMainNanozymePipeline.__init__ 增加 ExtractionVerifier 导入
  - extract() 方法中 VLM 合并后增加全记录验证步骤，验证数据传入 diag_builder

- `consistency_guard.py`
  - 新增 `detect_cross_context_mismatches()` 方法
  - 集成到 `validate_record_consistency()` 中

- `diagnostics_builder.py`
  - WARNING_ENUMS 增加 6 个验证相关枚举
  - DiagnosticsBuilder 增加 `_verification` 字段和 `set_verification()` 方法
  - `build()` 方法中合并 verification 信息，根据 verification_rate 调整 confidence

## 未改动内容
- `llm_extractor.py` — LLM 提取逻辑未改动（System Prompt 已要求 evidence_text）
- `vlm_extractor.py` — VLM 提取逻辑未改动
- `numeric_validator.py` — 数值校验逻辑未改动
- `cross_validation_agent.py` — 交叉验证逻辑未改动

## 验证方式
- 所有模块 import 成功
- ExtractionVerifier 单元测试通过：
  - Km=0.15 在原文中找到 → verified
  - Vmax=3.2e-8 在原文中找到 → verified（支持 E-notation）
  - Km=99.99 不在原文中 → hallucination_suspect
  - enzyme_like_type="peroxidase-like" 在原文中找到 → verified
  - synthesis_method="hydrothermal" 在原文中找到 → verified
  - synthesis_method="sol-gel" 不在原文中 → unverified
  - 验证率计算正确（4/4=1.0, 2/4=0.5）

## 风险与后续
- 验证系统依赖 evidence_text 的完整性，规则提取阶段的 evidence 覆盖率需要持续监控
- 数值回查的容差设置（5%精确匹配、15%近似匹配）可能需要根据实际数据调整
- 后续可考虑增加 LLM 二次验证（对 hallucination_suspect 字段用 LLM 确认是否为幻觉）
- 验证报告中的 field_status 可用于前端展示，提升用户对提取结果的信任度
