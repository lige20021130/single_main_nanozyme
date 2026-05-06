# 规则提取能力上限优化

## 更新时间
2026-05-06 22:30

## 更新类型
- 功能开发

## 背景
当前规则提取系统的覆盖率远低于LLM提取，关键字段差距：
- Km: 规则50-60% vs LLM ~80%（差距20-30%）
- Vmax: 规则40-50% vs LLM ~75%（差距25-35%）
- kcat: 规则10% vs LLM ~50%（差距40%）
- optimal_temperature: 规则20% vs LLM ~70%（差距50%）
- LOD: 规则40-50% vs LLM ~80%（差距30-40%）

根因：5大瓶颈——证据桶召回不足、动力学正则覆盖窄、应用提取漏检、pH/温度提取极弱、表格数据浪费。

## 改动内容

### 1. 增强证据桶召回（single_main_nanozyme_extractor.py）
- EvidenceBucketBuilder.max_sentences: 20→30
- kinetics/application/mechanism桶：在results/discussion节中，只要不是高置信度排除就纳入
- 解决：大量相关句子因未同时匹配材料名+关键词而被丢弃

### 2. 增强Km正则（+5个宽松模式）
- `Km...数字+单位`（50字符内宽松匹配）
- `Km...数字×10^-n+单位`（科学计数法）
- `Michaelis...constant...数字+单位`
- `Km...determined...数字+单位`
- `Km...数字e-n+单位`（E记法）

### 3. 增强Vmax正则（+5个宽松模式）
- `Vmax...数字+速率单位`（50字符内宽松匹配）
- `Vmax...数字×10^-n+速率单位`
- `maximum velocity...数字+速率单位`
- `Vmax...determined...数字+速率单位`
- `Vmax...数字e-n+速率单位`

### 4. 增强kcat正则（+7个模式）
- `kcat...数字×10^n s^-1`
- `turnover frequency...数字×10^n s^-1`
- `catalytic rate...数字×10^n s^-1`
- `kcat...数字s⁻¹`
- `Kcat...数字s^-1`（50字符内）
- `turnover number/frequency...数字s^-1`

### 5. 增强kcat/Km正则（+3个模式）
- `catalytic efficiency...数字×10^n M^-1s^-1`
- `specificity constant...数字×10^n M^-1s^-1`
- `kcat/Km...数字e-n M^-1s^-1`

### 6. 增强pH模式（+3个模式）
- `pH optimum was 数字`
- `maximum activity at pH 数字`
- `best/highest catalytic activity at/was pH 数字`

### 7. 增强温度模式（+5个模式）
- `optimal temperature of/was/at 数字°C`（Unicode度符号）
- `optimum temperature of/was/at 数字°C`
- `temperature optimum...数字°C`
- `maximum activity at 数字°C`
- `best/highest catalytic activity at 数字°C`

### 8. 增强LOD模式（+4个模式）
- `LOD for/of X was 数字×10^-n 单位`
- `as low as 数字 单位`
- `detected/detection down to/at 数字 单位`
- `LOD(数字×10^-n 单位)`

### 9. 增强linear_range模式（+2个模式）
- `range/concentration range of 数字-数字 单位`
- `数字-数字 单位 linear/calibration`

### 10. 增强应用提取（extraction_agents.py）
- ApplicationAgent搜索范围扩展：application桶 + kinetics桶前5 + activity桶前3
- 新增4个analyte模式：sensing/detecting/monitoring of、蛋白质/抗生素/农药关键词

### 11. 增强表格数据提取（extraction_agents.py）
- KineticsAgent._extract_kinetics_from_table增加行级正则回退
- 当结构化参数提取失败时，对表格raw_text应用_KM_PATTERNS正则匹配

## 未改动内容
- LLM/VLM提取管道未改动
- 交叉验证逻辑未改动
- 一致性修正逻辑未改动
- Schema验证未改动
- GUI未改动

## 验证方式
- `python -m py_compile single_main_nanozyme_extractor.py` 通过
- `python -m py_compile extraction_agents.py` 通过
- `python -m pytest tests/ -v --tb=short` 110 passed, 0 failed

## 风险与后续
- 宽松正则可能增加误匹配，需通过实际文献批量测试验证
- 后续应建立正则覆盖率回归测试集
- 可考虑对新增宽松模式增加置信度标记（如"loose_match"），在交叉验证中降权
