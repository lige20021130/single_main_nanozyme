# 全流程提取测试与系统优化

## 更新时间
2026-05-03 20:35

## 更新类型
- Bug 修复 / 功能优化 / 测试

## 背景
使用2021.6.1目录下大小前十的文献PDF进行真实全流程提取测试，发现多个系统性质量问题，从机制层面进行修复。

## 测试结果

### 第一轮测试（优化前）
- 8篇成功提取，2篇失败（1 PARSE_FAILED + 1 EXTRACT_FAILED）
- 平均质量评分：63.2/100
- 主要问题：Km/Vmax单位互换、材料名称截断/错误、detection兼容性误报、动力学数据缺失、pH/温度缺失

### 第二轮测试（优化后）
- 平均质量评分：63.0/100（评分标准未变，但关键数据准确性提升）
- Km/Vmax值互换已修复（Co-Fe LDHs: Km从8.52e-06修正为848.42）
- OCR碎片I385/I375已被过滤
- detection→sensing归一化完全生效，兼容性误报消除
- FeOOH@Fe名称更完整

## 改动内容

### 1. Km/Vmax单位类型校验（single_main_nanozyme_extractor.py）
- 新增 `_validate_and_assign_kinetics_unit()` 辅助函数
- `_merge_vlm` 中Km/Vmax单位赋值增加浓度/速率单位校验
- `_merge_llm` 中所有单位赋值点替换为校验函数
- `_backfill_kinetics_from_important_values` 增加单位类型校验
- 错误单位（如Km_unit="M/s"）不再赋值，记录警告

### 2. Km/Vmax值互换修复（extraction_agents.py）
- `_extract_kinetics_from_text` 中联合模式匹配增加单位类型校验
- 当group(1)的单位是速率单位、group(3)的单位是浓度单位时，自动交换Km/Vmax赋值
- 新增 `_validate_kinetics_units()` 方法，在KineticsAgent提取后校验并清除错误单位

### 3. 材料名称提取优化（single_main_nanozyme_extractor.py）
- `_extract_title_material` 增加SA/SAN/SAC/SAzyme缩写识别
- `_clean_candidate_name` 仅在名称过长(>25字符)时截断，避免过度截断
- `NanozymeScorer.score` 增加复合名称加分（含@/加5分，含数字加2分，SA缩写加3分）
- `NanozymeScorer.score` 增加标题金属元素匹配加分（+8分）
- `_SENTENCE_ID_RE` 扩展为过滤所有字母+数字编号格式（如I385/I375）

### 4. detection兼容性修复（consistency_agent.py + single_main_nanozyme_extractor.py）
- ConsistencyAgent 新增 `normalize_application_types()` 方法
- 在 `normalize_output` 流程中，于兼容性检查前执行application_type归一化
- 新增 `_APP_TYPE_ALIASES` 映射表（detection→sensing等）
- `validate_schema` 中增加最终归一化保障，确保无detection残留

### 5. 动力学数据提取增强（extraction_agents.py）
- KineticsAgent.extract 增加activity bucket回退搜索
- 当kinetics bucket未找到Km/Vmax时，扩展搜索到activity bucket

### 6. pH/温度最适条件提取增强（extraction_agents.py）
- `_extract_pH_profile` 扩展搜索范围（增加mechanism bucket、raw_supporting_text）
- 新增4个optimal_pH额外匹配模式
- `_extract_temperature_profile` 扩展搜索范围
- 新增3个optimal_temperature额外匹配模式

## 未改动内容
- PDF解析模块（opendataloader_pdf）未改动
- 预处理器（nanozyme_preprocessor_midjson.py）未改动
- VLM提取器（vlm_extractor.py）未改动
- LLM提取器（llm_extractor.py）未改动
- 配置管理器（config_manager.py）未改动

## 验证方式
- 运行 `python test/full_test_top10.py --force --limit 8` 进行全流程测试
- 对比优化前后提取结果，确认关键数据准确性提升
- Km/Vmax值互换修复：Co-Fe LDHs论文Km从8.52e-06修正为848.42
- OCR碎片过滤：I385/I375不再出现在候选材料中
- detection归一化：所有"detection vs peroxidase-like不兼容"警告消除

## 风险与后续
- **仍存在的问题**：
  1. Pt nanozymes材料名仍错误（GSH/100而非DPC@Pt@M）——需要更智能的候选材料召回策略
  2. Au@MA名称不完整（缺少Co-Fe LDHs前缀）——需要改进复合名称拼接逻辑
  3. Mo Single未修正为Mo-SAN——SA缩写识别可能未被候选召回覆盖
  4. 动力学数据提取率仍低（5/8篇缺失）——需要增强LLM prompt或增加更多正则模式
  5. optimal_pH/optimal_temperature仍普遍缺失——需要VLM图表分析增强
- **下一步建议**：
  1. 改进CandidateRecaller的标题材料提取，增加对"X-SAN"/"X-SAC"等缩写的完整识别
  2. 在NanozymeScorer中增加"载体vs活性材料"区分逻辑
  3. 增强LLM提取prompt中的动力学数据提取指令
  4. 对VLM增加pH/温度曲线图的专门分析prompt
