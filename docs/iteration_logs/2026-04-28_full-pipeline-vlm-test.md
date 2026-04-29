# 规则提取全面扩充 - kcat/kcat_Km增强

## 更新时间
2026-04-28 20:00

## 更新类型
- 功能开发 / Bug 修复

## 背景
全链路测试显示kcat提取率为0%，根因分析发现：
1. `_extract_kinetics_from_table` 完全不处理kcat/kcat_Km（只处理Km和Vmax）
2. `_KCAT_PATTERNS`只有7个模式，远少于Km(9个)和Vmax(16个)
3. `_KCAT_KM_PATTERNS`只有4个模式，单位匹配太窄
4. E记数法格式（如`1.400000e8`）未被kcat提取覆盖
5. 表格数据中kcat参数被直接跳过

## 改动内容

### 1. 扩充_KCAT_PATTERNS (7→13个)
- 新增`kcat = X s^-1`简单等号格式
- 新增宽松匹配`kcat...was X s⁻¹`（30字符窗口）
- 新增`kcat X × 10⁻N s⁻¹`科学计数法宽松格式
- 新增`kcat Xe-N s⁻¹`E记数法宽松格式
- 新增大写`Kcat`开头格式
- 新增`kcat(substrate) = X s⁻¹`带底物等号格式

### 2. 扩充_KCAT_KM_PATTERNS (4→10个)
- 新增无底物`kcat/Km = X M⁻¹s⁻¹`格式
- 新增`kcat/Km(substrate) = X M⁻¹s⁻¹`格式
- 新增E记数法`kcat/Km Xe-N M⁻¹s⁻¹`格式
- 新增科学计数法`kcat/Km X × 10⁻N M⁻¹s⁻¹`格式
- 新增`catalytic efficiency of X`格式
- 新增`specificity constant of X`格式
- 新增`kcat / Km`（有空格）格式
- 扩展单位匹配：`M⁻¹·s⁻¹`、`M/s`、`M⁻¹s⁻¹`、`M⁻¹ s⁻¹`等

### 3. 修复_extract_kinetics_from_table
- 新增kcat参数处理：`param in ("kcat", "Kcat", "k_cat")`
- 新增kcat_Km参数处理：`param in ("kcat/Km", "kcat_Km", "Kcat/Km", "catalytic_efficiency")`
- 使用`_parse_scientific_notation`解析科学计数法值
- 设置默认单位：kcat→`s^-1`，kcat/Km→`M^-1 s^-1`

### 4. 增强_extract_kcat_from_text
- 新增E记数法kcat提取：`kcat = 1.4e8` → `1.4 × 10^8`
- 新增E记数法kcat/Km提取：`kcat/Km = 1.4e8` → `1.4 × 10^8`
- 新增catalytic efficiency E记数法提取
- 所有E记数法提取后验证量级范围

## 测试结果

### 优化前 vs 优化后
| 指标 | 优化前 | 优化后 | 变化 |
|------|--------|--------|------|
| Km | 5/10 (50%) | 6/10 (60%) | +10% |
| Vmax | 4/10 (40%) | 5/10 (50%) | +10% |
| kcat | 0/10 (0%) | 1/10 (10%) | +10% |
| kcat/Km | 0/10 (0%) | 1/10 (10%) | +10% |

### 关键突破
- **FeN3P-SAzyme**: kcat=7.77e+05 s^-1, kcat/Km=1.40e+08 M-1 min-1 ✅
  - 之前kcat/Km提取到但kcat反推未触发
  - 现在E记数法直接匹配成功

### 仍存在的问题
- 9/10文献kcat仍为None（多数文献确实不含kcat数据）
- LLM名称不匹配仍导致3篇文献数据丢失
- Vmax单位仍有问题（"×10⁻²"不是有效单位）

## 未改动内容
- LLM合并冲突逻辑未修改（这是数据一致性保护，不是bug）
- ConsistencyGuard拒绝逻辑未修改
- VLM过滤策略未调整
- kcat反推逻辑条件未修改（用户确认条件正确）

## 验证方式
- 运行全链路测试：10篇真实文献
- 临时测试脚本已清理

## 风险与后续
- 新增正则模式可能存在误匹配，需在更多文献上验证
- kcat提取率10%仍偏低，但考虑到多数文献不含kcat数据，实际覆盖率可能已接近上限
- 建议下一步：换一批含kcat数据的文献专门验证
