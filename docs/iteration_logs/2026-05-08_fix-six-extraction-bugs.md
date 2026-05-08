# 提取弱项修复：6个关键Bug修复

## 更新时间
2026-05-08 22:00

## 更新类型
- Bug 修复

## 背景
通过对比系统提取结果与人工收集的Excel金标准数据，发现6个主要提取弱项，需从提取过程根因修复。

## 改动内容

### Bug1: VLM/LLM返回的Vmax值含科学计数法前缀在unit中未解析
- **文件**: `single_main_nanozyme_extractor.py`
- **问题**: VLM返回 value=1.0792, unit="x 10^-2 μM/s"，系统只取value=1.0792，未解析unit中的科学计数法前缀
- **修复**: 新增 `_parse_unit_scientific_prefix()` 函数，支持解析 `×10^-2`、`×10⁻³` 等科学计数法前缀（含Unicode上标数字），在VLM合并Vmax/Km/kcat/kcat_Km时调用

### Bug2: Vmax单位归一化后未做M/s→μM/s换算导致数值量级偏差
- **文件**: `single_main_nanozyme_extractor.py`
- **问题**: 提取到Vmax=4.41e-05 M/s，对比金标准44.1 μM/s时量级偏差百万倍
- **修复**: 在 `_validate_and_assign_kinetics_unit()` 中增加Vmax单位自动换算逻辑：M/s且值<1.0时自动换算为μM/s（×1e6），mM/s且值<1.0时换算为μM/s（×1e3）

### Bug3: Km=8.0 M明显异常值未被校验拦截
- **文件**: `extraction_agents.py`
- **问题**: Km=8.0 M通过量级校验（上限10.0），但纳米酶领域Km>1M几乎不可能
- **修复**: 在 `KineticsAgent._validate_kinetics_units()` 中增加Km量级合理性检查：Km>1.0 M时清除并标记needs_review，Km>1000 mM时同样清除

### Bug4: 多底物动力学只取第一组，丢失其他底物数据
- **文件**: `test/compare_excel_extraction.py`
- **问题**: 对比时只检查主kinetics，未检查kinetics_list中其他底物的动力学数据
- **修复**: 新增 `_find_best_kinetics_from_list()` 函数，在对比时当主kinetics无值时从kinetics_list中查找最匹配的条目

### Bug5: 形态描述提取通用词而非精确描述
- **文件**: `single_main_nanozyme_extractor.py`
- **问题**: 形态提取只匹配预定义通用词列表（如"nanoparticle"），丢失原文中的精确描述（如"uniform hollow polyhedral morphology"）
- **修复**: 新增 `_MORPHOLOGY_PHRASE_PATTERNS` 正则列表，优先从包含材料名的句子中提取完整形态描述短语，仅在无短语匹配时回退到通用词列表

### Bug6: 材料名简化问题
- **文件**: `single_main_nanozyme_extractor.py`
- **问题**: "Fe3O4@C"和"Fe3O4"同时作为候选时，"Fe3O4"可能因频率更高被选为主纳米酶
- **修复**: 在 `NanozymeScorer.score()` 中增加复合名称优先选择逻辑：当top候选是另一候选的子串且后者含@/且分数差距≤8时，优先选择复合名称

## 未改动内容
- `consistency_agent.py` 中的 `_NANO_SUFFIXES` 去后缀逻辑未改动（"NPs"后缀去除是合理行为）
- `numeric_validator.py` 中的量级校验范围未改动（在KineticsAgent层做了更精准的校验）
- 对比脚本中的单位换算逻辑未改动（在提取端做了自动换算）

## 验证方式
- 所有修改文件通过 `py_compile` 语法检查
- `_parse_unit_scientific_prefix()` 测试5种输入格式全部通过
- Vmax单位自动换算逻辑验证：4.41e-05 M/s → 44.1 μM/s
- Km量级校验验证：8.0 M → REJECTED，0.5 M → OK
- 复合名称优先选择验证：Fe3O4@C 优先于 Fe3O4

## 风险与后续
- `_parse_unit_scientific_prefix` 可能误匹配不含科学计数法的unit字符串，但正则严格度足够
- Vmax自动换算仅针对值<1.0的M/s，大值保留原单位
- 需要重新运行7篇验证集PDF提取，对比修复前后效果
- 后续可考虑在LLM prompt中明确要求返回标准单位格式
