# 多智能体架构进化 — 高质量纳米酶文献提取系统

## 更新时间
2026-04-29 20:10

## 更新类型
- 架构调整 / 功能开发

## 背景
当前系统经过多轮优化后，关键字段提取率仍不理想（Vmax~40%、kcat~25%），且存在双管线逻辑分裂、合并策略缺陷、归一化不一致三大架构级问题。核心瓶颈不再是单一正则或校验规则，而是提取流程缺乏专业化分工和交叉验证机制。

## 改动内容

### 新增文件
- `extraction_agents.py` — 4个专业Agent + RuleExtractorAdapter
  - KineticsAgent：动力学参数提取（Km/Vmax/kcat/kcat_Km）
  - MorphologyAgent：形貌参数提取（size/morphology/surface_area等）
  - SynthesisAgent：合成信息联合提取（method+temperature+time+precursors）
  - ApplicationAgent：应用信息提取（增强substrate/analyte区分）
  - RuleExtractorAdapter：适配器，保持向后兼容

- `cross_validation_agent.py` — 交叉验证Agent
  - 多数投票逻辑（规则/LLM/VLM三源一致性检测）
  - 截断前缀检测（规则值是LLM值截断时使用LLM值）
  - 量级合理性判断
  - 冲突解决策略
  - VLM sensing_performance参与applications构建

- `consistency_agent.py` — 一致性保障Agent
  - 酶类型归一化统一为连字符格式（peroxidase-like）
  - 单位输出统一归一化
  - 材料名称去除冗余后缀
  - 应用去重
  - 跨字段一致性检查

### 修改文件
- `single_main_nanozyme_extractor.py`
  - __init__中加载RuleExtractorAdapter、CrossValidationAgent、ConsistencyAgent
  - extract()中用CrossValidationAgent.merge_results替代_merge_llm/_merge_vlm
  - extract()中在validate_schema前调用ConsistencyAgent.normalize_output
  - 修复_merge_vlm中Km/Vmax冲突检测死代码

- `single_record_assembler.py`
  - 添加DeprecationWarning，标记独立合并路径废弃

- `diagnostics_builder.py`
  - WARNING_ENUMS从12种扩充至25+种
  - 新增compute_field_coverage方法
  - 新增regex_hit_stats类变量追踪
  - 新增generate_batch_report批量报告函数

## 未改动内容
- RuleExtractor原始类保留（作为fallback）
- _merge_llm/_merge_vlm原始方法保留（作为fallback）
- 正则模式库未修改
- LLM/VLM提取逻辑未修改
- 预处理器未修改

## 验证方式
- 单元测试全部通过（8个测试模块）
- KineticsAgent：Km=0.15提取正确，Vmax=3e-8提取正确
- MorphologyAgent：size=50nm、surface_area=120.5 m²/g提取正确
- SynthesisAgent：hydrothermal method、180°C、12h提取正确
- ApplicationAgent：2个应用提取正确，substrate/analyte区分正确
- CrossValidationAgent：5种场景（两源一致/截断/单源/冲突/三源一致）验证通过
- ConsistencyAgent：酶类型下划线→连字符、材料名去除后缀、应用去重、单位归一化验证通过
- DiagnosticsBuilder：field_coverage和batch_report验证通过

## 风险与后续
- extraction_agents.py从主提取器导入正则模式，如果主提取器重构需同步更新
- CrossValidationAgent的merge_results与原_merge_llm/_merge_vlm行为略有差异（更智能但可能改变部分边界case的结果）
- 真实文献全链路测试需要NanozymePreprocessor可用，当前仅单元测试验证
- 后续建议：增加更多正则模式覆盖常见文献表述、优化LLM prompt提高Vmax/kcat提取率
