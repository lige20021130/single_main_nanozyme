# Tasks

- [ ] Task 1: NumericValidator 校验策略放宽 — 放宽量级范围、Lineweaver-Burk/figure_candidate 改为 needs_review、扩充单位集合
  - [ ] SubTask 1.1: 放宽 _MAGNITUDE_RANGES 下限（Km→1e-12, Vmax→1e-15, kcat→1e-6, kcat_Km→1e-3），超出原范围的值标记 needs_review=True
  - [ ] SubTask 1.2: Lineweaver-Burk 数据从硬性拒绝改为 needs_review=True 标记
  - [ ] SubTask 1.3: figure_candidate 来源从硬性拒绝改为 needs_review=True 标记
  - [ ] SubTask 1.4: 扩充 CONCENTRATION_UNITS 和 RATE_UNITS 集合，添加 M/L、mM/L、M/h、mM/h 等变体
  - [ ] SubTask 1.5: 增强 normalize_unit 处理 M/L、mol/L/s、uM/min 等变体

- [ ] Task 2: 候选材料选择准确率提升 — 复合材料拆分、关联评分、排除列表扩展
  - [ ] SubTask 2.1: 在 CandidateRecaller 中添加复合材料拆分逻辑（@、/、-分隔符），优先选择含金属元素的子组件
  - [ ] SubTask 2.2: 在 NanozymeScorer 中添加候选材料与酶活类型的关联性评分加分
  - [ ] SubTask 2.3: 扩展 _REAGENT_NAMES 排除列表，添加 RPMI-1640、DMEM、FBS、培养基变体等

- [ ] Task 3: LLM/规则合并策略智能化 — 规则值为None时采用LLM值、LLM补充字段、来源标记
  - [ ] SubTask 3.1: 修改 _merge_llm，当规则 Km/Vmax/kcat/kcat_Km 为 None 时直接采用 LLM 值，无需量级检查
  - [ ] SubTask 3.2: 修改 _merge_llm，当 LLM 提供了规则未提取的字段时自动补充
  - [ ] SubTask 3.3: 合并后的字段添加来源标记（source: "llm_supplement" 或 "rule"）

- [ ] Task 4: 输出一致性保障 — 单位格式统一、酶类型命名统一、材料名称格式统一
  - [ ] SubTask 4.1: 在 validate_schema 中统一单位输出格式（mM·s⁻¹ → mM/s 等）
  - [ ] SubTask 4.2: 在 nanozyme_models.py 中增强酶类型归一化（peroxidase (POD)-like → peroxidase-like）
  - [ ] SubTask 4.3: 在 single_record_assembler.py 中去除材料名称冗余后缀（nanoparticles、NPs、nanozyme 等）

- [ ] Task 5: 全链路验证 — 用10篇文献验证改革效果
  - [ ] SubTask 5.1: 运行全链路测试（LLM模式），收集关键字段填充率
  - [ ] SubTask 5.2: 对比改革前后数据，确认提升效果
  - [ ] SubTask 5.3: 更新迭代记录

# Task Dependencies
- [Task 5] depends on [Task 1, Task 2, Task 3, Task 4]
- [Task 1, Task 2, Task 3, Task 4] are independent and can be parallelized
- [SubTask 1.5] depends on [SubTask 1.4] (单位集合先扩充，再增强归一化)
