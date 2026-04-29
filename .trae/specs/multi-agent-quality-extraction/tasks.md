# Tasks

- [ ] Task 1: 提取Agent专业化拆分 — 将RuleExtractor拆分为四个专业Agent
  - [ ] SubTask 1.1: 创建KineticsAgent类，迁移动力学参数提取正则和逻辑（Km/Vmax/kcat/kcat_Km共51个正则模式），增加confidence_score和evidence_text返回
  - [ ] SubTask 1.2: 创建MorphologyAgent类，迁移形貌参数提取逻辑（size/morphology/surface_area/zeta_potential/pore_size/crystal_structure），增加联合提取能力
  - [ ] SubTask 1.3: 创建SynthesisAgent类，迁移合成信息提取逻辑（synthesis_method/temperature/time/precursors），实现温度-时间-前驱体联合提取避免碎片化
  - [ ] SubTask 1.4: 创建ApplicationAgent类，迁移应用信息提取逻辑（application_type/target_analyte/LOD/linear_range/sample_type），增强substrate/analyte区分
  - [ ] SubTask 1.5: 修改SingleMainNanozymePipeline.extract()，用四个Agent替代原RuleExtractor调用，保持向后兼容

- [ ] Task 2: 交叉验证Agent — 新增CrossValidationAgent实现多源交叉验证
  - [ ] SubTask 2.1: 创建CrossValidationAgent类，实现多数投票逻辑（规则/LLM/VLM三源一致性检测）
  - [ ] SubTask 2.2: 实现截断前缀检测（规则值是LLM值的截断时使用LLM值）
  - [ ] SubTask 2.3: 实现量级合理性判断（结合NumericValidator的范围检查）
  - [ ] SubTask 2.4: 实现冲突解决策略（无法解决时保留规则值+LLM存_alternative+标记needs_review）
  - [ ] SubTask 2.5: 修改_merge_llm和_merge_vlm，集成CrossValidationAgent替代原有简单合并逻辑

- [ ] Task 3: 一致性保障Agent — 新增ConsistencyAgent统一输出格式
  - [ ] SubTask 3.1: 统一酶类型归一化为连字符格式（peroxidase-like），修改activity_selector.py的normalize_enzyme_type输出格式
  - [ ] SubTask 3.2: 统一单位输出格式，在validate_schema最终输出前对所有单位字段调用normalize_unit
  - [ ] SubTask 3.3: 统一材料名称格式，去除冗余后缀（nanoparticles/NPs/nanosheets/nanocubes/nanorods/nanozyme等）
  - [ ] SubTask 3.4: 实现应用去重逻辑，基于(application_type, target_analyte)二元组合并重复应用
  - [ ] SubTask 3.5: 增强跨字段一致性检查（Km单位浓度验证、Vmax单位速率验证、kcat-Km量级合理性、酶类型-pH逻辑一致性）

- [ ] Task 4: 双管线统一 — 废弃SingleRecordAssembler独立合并路径
  - [ ] SubTask 4.1: 修复_merge_vlm中Km冲突检测死代码（条件逻辑错误导致VLM值无法填充空值）
  - [ ] SubTask 4.2: 使VLM的sensing_performance（LOD/linear_range）参与applications构建而非仅写入important_values
  - [ ] SubTask 4.3: 将SingleRecordAssembler的独立合并逻辑标记为废弃，保留数据结构定义辅助方法
  - [ ] SubTask 4.4: 确保SingleMainNanozymePipeline.extract()为唯一入口，外部调用统一走此路径

- [ ] Task 5: 诊断与覆盖率追踪 — 扩充诊断系统
  - [ ] SubTask 5.1: 扩充WARNING_ENUMS，添加所有模块产生的警告类型（Km_unit_not_concentration、material_mismatch、attribution_mismatch等）
  - [ ] SubTask 5.2: 在diagnostics中增加field_coverage字典，记录每个字段的提取状态（extracted/missing/default）
  - [ ] SubTask 5.3: 增加regex_hit_stats追踪，记录每个正则模式的命中次数
  - [ ] SubTask 5.4: 实现批量提取率汇总报告功能，按字段统计提取率百分比

- [ ] Task 6: 全链路验证 — 用10篇文献验证进化效果
  - [ ] SubTask 6.1: 运行全链路测试（LLM+VLM模式），收集关键字段填充率
  - [ ] SubTask 6.2: 对比进化前后数据，确认准确率和一致性提升效果
  - [ ] SubTask 6.3: 更新迭代记录

# Task Dependencies
- [Task 2] depends on [Task 1] (交叉验证需要专业化Agent先产出结构化结果)
- [Task 3] depends on [Task 1] (一致性保障需要专业化Agent的输出格式统一)
- [Task 4] depends on [Task 2, Task 3] (双管线统一需要交叉验证和一致性保障就绪)
- [Task 5] depends on [Task 1] (诊断追踪需要专业化Agent的提取结果)
- [Task 6] depends on [Task 1, Task 2, Task 3, Task 4, Task 5]
- [Task 1] 的 SubTask 1.1-1.4 可并行开发
- [Task 3] 的 SubTask 3.1-3.5 可并行开发
