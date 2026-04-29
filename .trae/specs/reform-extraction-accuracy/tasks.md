# Tasks

- [x] Task 1: kinetics bucket fallback机制 — EvidenceBucketBuilder.build中为kinetics/application/mechanism bucket增加fallback
  - [x] SubTask 1.1: 在EvidenceBucketBuilder.build中，当严格过滤后kinetics bucket为空时，使用宽松过滤策略重新填充
  - [x] SubTask 1.2: 在diagnostics中记录"kinetics_bucket_fallback_applied"警告
  - [x] SubTask 1.3: 对application和mechanism bucket同样增加fallback

- [x] Task 2: OCR修复重构 — 扩充_OCR_FIXES覆盖范围，修正_OCR_COMPOUND_FIXES误伤
  - [x] SubTask 2.1: 扩充_OCR_FIXES，增加Ce/Ag/Ti/V/Cr/Mo/W/Ru/Rh/Ir/La等金属的双字母修复规则
  - [x] SubTask 2.2: 修正_OCR_COMPOUND_FIXES，增加上下文判断避免误伤合法化学式（如Fe3C）
  - [x] SubTask 2.3: 增加数字OCR修复规则（O/0混淆）

- [x] Task 3: 合并策略智能判断 — _merge_llm中>10倍差异时判断规则值可靠性
  - [x] SubTask 3.1: 在>10倍差异处理中，增加"规则值是否为LLM值的截断前缀"判断
  - [x] SubTask 3.2: 增加"规则值是否在合理量级范围外"判断
  - [x] SubTask 3.3: 不可靠规则值时使用LLM值替换

- [x] Task 4: 单位在提取阶段归一化 — 规则提取写入单位时立即调用normalize_unit
  - [x] SubTask 4.1: 在_extract_kinetics_from_text中，写入Km_unit/Vmax_unit前调用normalize_unit
  - [x] SubTask 4.2: 在_extract_kinetics_from_table中，写入单位前调用normalize_unit
  - [x] SubTask 4.3: 在_extract_kcat_from_text中，写入kcat_unit/kcat_Km_unit前调用normalize_unit

- [x] Task 5: 全链路验证 — 用10篇文献验证改革效果
  - [x] SubTask 5.1: 运行全链路测试，收集关键字段填充率
  - [x] SubTask 5.2: 对比改革前后数据，确认提升效果
  - [x] SubTask 5.3: 更新迭代记录

# Task Dependencies
- [Task 5] depends on [Task 1, Task 2, Task 3, Task 4]
- [Task 1, Task 2, Task 3, Task 4] are independent and can be parallelized
