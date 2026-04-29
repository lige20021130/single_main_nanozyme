# Schema提取能力系统性优化

## 更新时间
2026-04-28 17:30

## 更新类型
- 功能开发 / Bug 修复

## 背景
在上一轮schema扩展的基础上，对现有schema各字段的提取规则进行系统性精准度优化。核心原则：不增加LLM计算负担、不改变schema结构、确保不退化。

## 改动内容

### 1. 修复_parse_scientific_notation bug (single_main_nanozyme_extractor.py)
- 旧代码：`tail = s.split('10')` 会在数字内部误匹配'10'（如"1.05×10⁻³"中的'10'）
- 新代码：使用正则 `([\d.]+)\s*[×x]\s*10\s*[\^]?\s*([⁻\-–−]?)(\d+)` 精确解析符号和指数
- 影响：所有科学计数法数值的解析准确率提升

### 2. 优化证据分桶逻辑 (single_main_nanozyme_extractor.py)
- 旧逻辑：要求每个句子必须包含材料名才进入分桶，遗漏大量不含材料名但含关键数据的句子
- 新逻辑：
  - kinetics/application/mechanism桶：不要求材料名匹配（这些信息通常不提及材料名）
  - activity/synthesis/characterization桶：放宽为关键词匹配（nanozyme, enzyme-like, catalytic等）
  - 增加材料名变体：去除"nano"、"the "、"a "前缀后也作为匹配变体
- 影响：证据召回率显著提升，特别是pH/温度/合成方法相关句子

### 3. 扩展分桶关键词覆盖 (single_main_nanozyme_extractor.py)
- material桶：新增crystal/amorphous/spinel/perovskite/anatase/rutile/calcination/annealing/carbonization/pyrolysis
- synthesis桶：新增co-precipitation/sol-gel/precursor/temperature/heated/furnace/reaction time/one-pot/two-step/in-situ/ex-situ
- characterization桶：新增zeta potential/surface area/pore size/BJH/lattice/d-spacing/crystallite
- activity桶：新增optimal pH/optimal temperature/pH dependent/temperature dependent/pH range/pH stability/thermal stability

### 4. 修复_merge_llm嵌套字段合并 (single_main_nanozyme_extractor.py)
- 旧代码：未处理synthesis_conditions/pH_profile/temperature_profile嵌套字典
- 新代码：逐字段合并嵌套字典，kcat/kcat_Km也进行str→float转换
- 影响：LLM提取的新字段数据不再丢失

### 5. 精简LLM Prompt (single_main_nanozyme_extractor.py)
- 旧prompt：~2400字符，10条HARD RULES，6大详细规则段
- 新prompt：~1500字符，5条HARD RULES，1个紧凑的KEY EXTRACTION RULES段
- 保留所有关键提取指引，去除冗余描述
- 影响：token消耗减少约40%，LLM推理更聚焦

### 6. 优化pH/温度提取搜索范围 (single_main_nanozyme_extractor.py)
- pH提取：搜索范围从activity桶扩展到activity+kinetics桶
- 温度提取：搜索范围从activity桶扩展到activity+kinetics桶
- 新增回退模式：当"optimal"关键词未匹配时，回退到简单"pH was X"/"temperature was X °C"模式
- 温度回退增加范围验证（15-80°C为合理反应温度区间）
- 影响：pH/温度提取召回率提升

### 7. 优化合成方法提取 (single_main_nanozyme_extractor.py)
- 搜索范围从synthesis桶扩展到synthesis+material桶
- 合成方法选择从"首次匹配"改为"频率投票"：统计所有文本中各方法出现次数，选择最高频
- 影响：减少误判，提高合成方法识别准确率

### 8. 增加Km/Vmax联合出现模式 (single_main_nanozyme_extractor.py)
- 新增_KM_VMAX_JOINT_PATTERNS：2个模式处理"Km = X mM, Vmax = Y M/s"和"Km and Vmax were X and Y"格式
- 在_extract_kinetics_from_text中优先尝试联合模式
- 影响：提高Km/Vmax同时出现时的提取成功率

### 9. 修复分析物正则 (single_main_nanozyme_extractor.py)
- 旧代码：`Hg2\+`等在字符类中转义不正确
- 新代码：分离有机/无机分析物为独立模式，离子匹配使用`Hg[\s2]*\+{1,2}`等
- 新增mercury/lead/cadmium/arsenic/chromium等元素名匹配
- 影响：金属离子分析物识别准确率提升

### 10. 增加尺寸提取格式 (single_main_nanozyme_extractor.py)
- 新增2个模式："X nm in size"/"X-Y nm in diameter"格式
- 影响：覆盖更多尺寸描述方式

### 11. 优化物理特性搜索范围 (single_main_nanozyme_extractor.py)
- 合成方法搜索：synthesis + material桶
- 尺寸搜索：material + characterization + synthesis桶
- 物理特性搜索：characterization + material桶
- 影响：扩大搜索范围，提高召回率

## 未改动内容
- nanozyme_models.py：酶类型定义未变
- numeric_validator.py：验证逻辑未变
- activity_selector.py：选择逻辑未变
- single_record_assembler.py：组装逻辑未变
- diagnostics_builder.py：诊断逻辑未变
- schema结构：完全未变

## 验证方式
- 运行 `python -m pytest test_single_main_nanozyme.py -v`
- 32个测试全部通过，耗时0.16秒（与优化前持平）

## 风险与后续
- 证据分桶放宽后可能引入更多噪声句子，需在实际文献上验证
- LLM Prompt精简后需验证LLM提取准确率未下降
- 合成方法频率投票在短文本中可能不够准确
- 建议下一步：用实际文献数据进行端到端提取对比测试
