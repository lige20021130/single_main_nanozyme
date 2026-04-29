# GUI重设计与Vmax提取率系统性修复

## 更新时间
2026-04-28 02:00

## 更新类型
- 功能开发 / Bug 修复

## 背景
1. 原GUI界面布局混乱，所有功能堆叠在一个页面上，缺乏系统状态可视化
2. Vmax提取率为0%，经系统性诊断发现是正则模式根本性缺陷

## 改动内容

### 1. GUI界面重设计（pdf_basic_gui.py）

**设计原则**：
- 系统状态仪表板：顶部6个圆形指示器（●）实时显示各模块状态
- Notebook分页布局：3个Tab（文件与转换、智能提取、运行日志）
- ttk现代化控件：统一使用ttk组件替代tk组件
- 底部状态栏：显示当前状态和文件计数

**状态指示器**：
- PDF服务器：idle(灰) → running(橙) → ok(绿) / error(红)
- 文本大模型：idle(灰) → ok(绿) / disabled(灰)
- 视觉大模型：idle(灰) → ok(绿) / disabled(灰)
- PDF解析：idle(灰) → running(橙) → ok(绿)
- 预处理：idle(灰) → running(橙) → ok(绿)
- 智能提取：idle(灰) → running(橙) → ok(绿)

**新增方法**：
- `set_phase_status(phase, status)` — 设置阶段指示器颜色

### 2. Vmax提取系统性修复（single_main_nanozyme_extractor.py）

**诊断结果**：
| 文献 | 原文Vmax | 修复前 | 修复后 |
|------|---------|--------|--------|
| 2021_73e66402 | Vmax=7 x 10^-8 M s^-1 | None | 7e-08 ✅ |
| 2021_73e66402 | Vmax=30 x 10^-8 M s^-1 | None | 3e-07 ✅ |
| 2021_73e66402 | Vmax=16 x 10^-8 M s^-1 | None | 1.6e-07 ✅ |
| 2021_06a8d32c | 1.97 x 10-5 M s-1 | None | 1.97e-05 ✅ |
| 2021_36e77786 | V max 17.2 mM s^-1 | None | 待优化 |

**根本原因**：
1. Vmax正则不支持 `V max`（有空格）
2. 不支持 `Vmax=` 等号连接格式
3. 不支持 `x 10^-8` 科学计数法（有 `^` 符号）
4. 不支持 `M s^-1` 单位格式（有 `^` 符号）
5. `_parse_scientific_notation` 不匹配 `10^-8` 格式

**修复内容**：
1. 所有Vmax正则模式中 `Vmax` → `V\s*max`（支持空格）
2. 新增 `Vmax=` 等号连接模式（Pat4）
3. 科学计数法匹配增加 `[\^⁻\-–]?` 支持 `^` 符号
4. 单位匹配增加 `[\^⁻\-–]?[\-]?` 支持 `s^-1`
5. `_parse_scientific_notation` 正则增加 `\^` 支持
6. `_RATE_UNITS` 增加 `"M s^-1"` 变体
7. 新增Km/Vmax并列模式（Pat8）
8. 新增Vmax多值+误差模式（Pat9）

## 未改动内容
- `nanozyme_preprocessor_midjson.py`：未修改
- `vlm_extractor.py`：未修改
- `extraction_pipeline.py`：未修改
- `config.yaml`：未修改
- `test_single_main_nanozyme.py`：未修改

## 验证方式
- 32个单元测试全部通过
- GUI模块导入成功
- Vmax专项测试：4/5种格式通过
  - `Vmax=7 x 10^-8 M s^-1` → Vmax=7e-08 ✅
  - `Vmax=30 x 10^-8 M s^-1` → Vmax=3e-07 ✅
  - `Vmax=16 x 10^-8 M s^-1` → Vmax=1.6e-07 ✅
  - `1.97 x 10-5 M s-1` → Vmax=1.97e-05 ✅
  - `V max were 17.2 +/- 0.5 mM s^-1` → 待优化

## 风险与后续
- **Vmax多值+误差格式**：`V max were 17.2 +/- 0.5 and 11.4 +/- 0.4 mM s^-1` 仍无法匹配，需后续优化
- **GUI状态指示器联动**：`set_phase_status` 已定义但尚未在所有流程中调用，需后续集成
- **VLM提取值精度**：VLM从图片读取的Vmax值可能与文本值不一致，需交叉验证机制
