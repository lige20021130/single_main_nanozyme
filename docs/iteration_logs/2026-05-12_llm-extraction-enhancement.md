# LLM提取能力全面增强

## 更新时间
2026-05-12 22:00

## 更新类型
- 功能开发

## 背景
系统LLM提取能力存在瓶颈：kcat提取率仅10%、optimal_temperature仅20%、LOD约40-50%、JSON解析偶尔失败、表格数据提取效率低。需要从Prompt工程、Constrained Decoding、表格提取、自我验证四个维度全面增强。

## 改动内容

### 1. Prompt工程优化（extraction_prompts.py）
- 动力学few-shot examples从4个扩展到10个，覆盖多底物、kcat、kcat/Km、不同材料等场景
- 形态学few-shot examples从2个扩展到5个，覆盖核壳结构、多晶型、表面面积等
- 应用few-shot examples从2个扩展到5个，覆盖传感、抗菌、治疗、环境等
- 新增合成条件提取prompt（SYNTHESIS_EXTRACTION_PROMPT + 3个few-shot）
- 新增pH/温度提取prompt（PH_TEMP_EXTRACTION_PROMPT + 3个few-shot）
- 新增表格动力学提取prompt（TABLE_KINETICS_EXTRACTION_PROMPT + 3个few-shot）
- 新增验证prompt（VERIFICATION_PROMPT）
- SYSTEM_PROMPT增强：添加表格解读规则、单位转换表、SERS说明等12条领域知识

### 2. Constrained Decoding（schema_constraints.py + llm_structured_extractor.py）
- 新增Pydantic模型：KineticsEntryModel、SynthesisConditionsModel、ApplicationEntryModel、NanozymeExtractionModel
- ApplicationEntryModel包含application_type字段验证器
- llm_structured_extractor.py新增_call_with_instructor方法，支持instructor库结构化输出
- _call_llm_structured新增response_model参数，优先走instructor路径，失败自动降级到JSON模式
- instructor为可选依赖，不影响无instructor环境

### 3. 表格提取增强（llm_structured_extractor.py）
- 新增extract_from_table方法，专门处理表格数据提取动力学参数
- 新增_prepare_table_text方法，智能截断表格文本（优先保留表头和含Km/Vmax关键词行）
- 新增_merge_kinetics_results方法，合并文本提取和表格提取结果（文本优先，表格补充空字段，kinetics_list按substrate+material_variant去重合并）
- extract_kinetics方法更新：文本提取后追加表格提取+合并

### 4. 验证-修正循环（llm_structured_extractor.py）
- 新增_verify_and_correct方法，实现Extract→Verify→Correct循环
- 支持多轮验证（max_verification_rounds可配置，默认1轮）
- 验证prompt检查6类常见错误：错误值、错误单位、缺失数据、虚构数据、错误底物、单位转换错误
- extract_kinetics集成验证循环

### 5. 新增提取方法（llm_structured_extractor.py）
- 新增extract_synthesis方法：提取合成方法、条件、表征手段
- 新增extract_ph_temp方法：提取pH/温度最优值和范围
- extract_all更新：集成synthesis和ph_temp提取，非覆盖式合并（仅补充空字段）

## 未改动内容
- single_main_nanozyme_extractor.py（核心大文件）未修改
- extraction_pipeline.py未修改
- cross_validation_agent.py、consistency_agent.py等验证层未修改
- nanozyme_models.py数据模型未修改
- GUI层未修改

## 验证方式
- 全量测试152个用例全部通过
- llm_structured_extractor测试22个用例全部通过
- schema_constraints测试20个用例全部通过
- 语法检查全部通过

## 风险与后续
- instructor库为可选依赖，需用户手动安装（pip install instructor）
- 验证-修正循环会增加1-2次LLM调用，可能影响提取速度
- 后续可通过实际文献测试评估各增强点的提取率提升效果
- 建议在config.yaml中添加enable_verification和max_verification_rounds配置项
