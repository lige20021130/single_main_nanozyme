# P0-P2提取系统瓶颈修复

## 更新时间
2026-05-04 04:30

## 更新类型
- Bug 修复 / 功能开发

## 背景
通过追踪预处理文本和提取结果的对比，发现提取系统存在5个关键瓶颈：
- P0: 信息在文本中但未提取（LOD/线性范围单位不匹配、合成方法退化）
- P0: SI表格不可达（Km/Vmax值在SI表格中但系统看不到）
- P1: 结构表征字段提取逻辑未激活（metal_elements/characterization始终为空）
- P2: 合并策略过于保守（"general synthesis"不被LLM好值覆盖）
- P2: 不可检测的盲区（系统不知道自己遗漏了什么）

## 改动内容

### P0-1: 扩展LOD/线性范围正则模式
- **文件**: `single_main_nanozyme_extractor.py`
- `_LOD_PATTERNS`: 新增U/L、mU/L、U/mL、ng/L、μg/L、mg/mL、pM、fM单位
- `_LOD_PATTERNS`: 新增科学计数法模式（×10⁻ⁿ）
- `_LINEAR_RANGE_PATTERNS`: 新增U/L、mU/L、U/mL单位
- `_LINEAR_RANGE_PATTERNS`: 新增"in/within the range of"模式

### P0-2: SI表格不可达警告 + 全文回退LOD/线性范围
- **文件**: `extraction_agents.py`
- `_fulltext_fallback_extract()`: 新增LOD全文回退搜索（对sensing类应用）
- `_fulltext_fallback_extract()`: 新增线性范围全文回退搜索
- `_fulltext_fallback_extract()`: 新增SI表格引用检测，当Km/Vmax为空且文中引用"Table S4 displays Km values"时产生`kinetics_in_SI_table_unreachable`警告

### P0-1续: SynthesisAgent评分优化
- **文件**: `extraction_agents.py` + `single_main_nanozyme_extractor.py`
- `general_synthesis`评分权重从1.0降为0.1
- 优先选择非generic方法，仅当所有方法都是generic时才选generic
- 两处代码同步修改（extraction_agents.py和主提取器）

### P1: 结构表征字段提取逻辑实现
- **文件**: `extraction_agents.py`
- `MorphologyAgent`: 新增`_METAL_ELEMENTS`列表（41个金属元素）
- `MorphologyAgent`: 新增`_CHARACTERIZATION_TECHNIQUES`字典（20种表征技术）
- `MorphologyAgent`: 新增`_extract_metal_elements()`方法，从材料名和文本中提取金属元素
- `MorphologyAgent`: 新增`_extract_characterization_techniques()`方法，从文本中识别表征技术

### P2-1: 合并策略优化
- **文件**: `single_main_nanozyme_extractor.py`
- `_merge_llm()`: 新增低质量规则值检测
- 当规则值为"general synthesis"等劣值时，LLM的非劣值可以覆盖
- 覆盖时记录`_llm_{key}_override_reason = "rule_value_low_quality"`

### P2-2: 增加"信息存在但未提取"的检测警告
- **文件**: `diagnostics_builder.py`
- 新增5个警告枚举：`kinetics_mentioned_but_not_extracted`、`LOD_mentioned_but_not_extracted`、`synthesis_method_generic`、`metal_elements_empty`、`characterization_empty`
- 新增`set_raw_text()`和`set_selected_nanozyme_full()`方法
- `build()`: 检测文中提及Km/Vmax但未提取、提及LOD但未提取、合成方法为generic、金属元素为空、表征技术为空

## 未改动内容
- Schema结构未改动
- LLM/VLM提取逻辑未改动
- 预处理器逻辑未改动
- ExtractionVerifier/ConsistencyGuard未改动

## 验证方式
- 代码导入验证：所有模块正常导入 ✅
- DiagnosticsBuilder单元测试：5个新警告全部正确触发 ✅
- MorphologyAgent：41个金属元素 + 20种表征技术 ✅
- 合并策略：低质量规则值时LLM可覆盖 ✅

## 风险与后续
- 金属元素提取可能误匹配（如"In"既是元素也是介词），需观察实际效果
- LOD全文回退可能匹配到非目标应用的LOD值
- SI表格不可达是输入层面问题，代码层面只能警告无法解决
- 下一步：运行全链路测评验证实际效果
