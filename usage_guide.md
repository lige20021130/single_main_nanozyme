# 纳米酶文献提取系统 - 使用指南

## 系统简介

本系统从纳米酶（Nanozyme）科研文献 PDF 中自动提取结构化数据，包括：
- 纳米酶材料名称、形态、尺寸
- 酶活性类型（过氧化物酶/氧化酶/过氧化氢酶等）
- 动力学参数（Km、Vmax、kcat）
- 应用信息（检测目标、检测限、方法）
- pH/温度最适条件

支持两种提取模式：
- **规则模式**：无需 API 密钥，基于正则表达式提取，精度中等
- **AI 模式**：需要 API 密钥，LLM 结构化提取 + 规则兜底，精度高

---

## 快速开始

### 1. 环境要求

| 项目 | 要求 |
|------|------|
| Python | 3.10 或更高版本 |
| 操作系统 | Windows 10/11（推荐），Linux，macOS |
| 内存 | ≥ 4 GB |
| 磁盘 | ≥ 500 MB（含依赖） |

### 2. 安装依赖

```bash
# 进入项目目录
cd single_main_nanozyme

# 安装依赖
pip install -r requirements.txt

# 安装 PDF 解析器（必需）
pip install opendataloader-pdf

# 可选：加速 JSON 解析
pip install orjson
```

### 3. 启动系统

**方式一：双击启动（Windows）**

双击 `start.bat` 文件即可启动。

> 如果闪退，请用方式二启动查看错误信息。

**方式二：命令行启动**

```bash
python start.py
```

**方式三：直接启动 GUI**

```bash
python nanozyme_gui.py
```

启动后系统会自动进行预检查：
- Python 版本检查
- 依赖包检查
- 核心文件检查
- 配置文件检查

如果所有检查通过，GUI 窗口会自动弹出。

---

## 配置 API 密钥（AI 模式）

### 方式一：GUI 自动生成

1. 启动系统后，点击「开始提取」
2. 如果没有 config.yaml，系统会提示是否自动生成模板
3. 点击「是」生成模板文件
4. 用文本编辑器打开 `config.yaml`，填入 API 密钥
5. 重启系统

### 方式二：手动创建

在项目根目录创建 `config.yaml`：

```yaml
providers:
  llm:
    model: deepseek-chat
    base_url: https://api.deepseek.com/v1
    api_key: sk-xxxxxxxxxxxxxxxxxxxxxxxx
    max_tokens: 8192
    temperature: 0.1

  vlm:
    model: Qwen/Qwen2-VL-7B-Instruct
    base_url: https://api.siliconflow.cn/v1
    api_key: sk-xxxxxxxxxxxxxxxxxxxxxxxx
    max_tokens: 4096

pipeline:
  enable_llm: true
  enable_vlm: true
  enable_cache: true
  per_document_timeout: 600
  results_dir: extraction_results
```

### 推荐的 LLM 服务商

| 服务商 | 模型 | base_url | 特点 |
|--------|------|----------|------|
| DeepSeek | deepseek-chat | https://api.deepseek.com/v1 | 性价比高，中文理解好 |
| 硅基流动 | Qwen2-VL-7B | https://api.siliconflow.cn/v1 | 支持 VLM 视觉模型 |
| OpenAI | gpt-4o | https://api.openai.com/v1 | 效果最好，价格较高 |

> **安全提示**：`config.yaml` 包含 API 密钥，已被 `.gitignore` 排除，不会被提交到 Git。

---

## 使用流程

### 完整流程（推荐）

```
选择PDF → 预处理 → 智能提取 → 查看结果
```

#### 步骤 1：选择 PDF 文件

- 点击「选择文件」选择一个或多个 PDF
- 或点击「选择文件夹」批量选择目录下所有 PDF
- 勾选「递归」可包含子目录中的 PDF

#### 步骤 2：预处理

- 点击「开始预处理」
- 系统会自动：解析 PDF → 提取文本/表格/图片 → 生成中间文件
- 预处理完成后，状态栏显示「预处理完成，可启动智能提取」

#### 步骤 3：智能提取

- 点击「开始提取」
- 系统会自动：LLM 提取 → 规则提取（兜底）→ 交叉验证 → 一致性修正 → 数值校验
- 提取完成后，结果保存在输出目录

#### 步骤 4：查看结果

- 点击「查看结果」打开提取结果 JSON
- 结果文件命名：`{PDF文件名}_extracted.json`

### 仅规则模式（无需 API）

如果未配置 API 密钥，系统自动使用规则模式：
1. 选择 PDF → 预处理
2. 点击「开始提取」→ 选择「否」（规则模式）
3. 规则模式不调用 LLM/VLM，提取精度较低但免费

### 命令行模式

```bash
# 从 PDF 直接提取
python run_extraction.py --input paper.pdf --output results

# 从已有 mid_task.json 提取
python run_extraction.py --mid-task paper_mid_task.json --output results

# 批量提取
python run_extraction.py --input-dir ./pdfs --output results

# 仅规则模式
python run_extraction.py --mid-task paper_mid_task.json --output results --no-llm --no-vlm

# 禁用缓存
python run_extraction.py --mid-task paper_mid_task.json --output results --no-cache
```

---

## 提取结果说明

### 输出 JSON 结构

```json
{
  "selected_nanozyme": {
    "name": "Fe3O4",
    "morphology": "spherical",
    "size": 20,
    "size_unit": "nm",
    "synthesis_method": "co-precipitation",
    "characterization": ["XRD", "TEM", "XPS"]
  },
  "main_activity": {
    "enzyme_like_type": "peroxidase-like",
    "substrates": ["TMB", "H2O2"],
    "kinetics": {
      "Km": 0.5,
      "Km_unit": "mM",
      "Vmax": 10.2,
      "Vmax_unit": "μM/s",
      "substrate": "TMB"
    },
    "kinetics_list": [
      {"Km": 0.5, "Km_unit": "mM", "Vmax": 10.2, "Vmax_unit": "μM/s", "substrate": "TMB"},
      {"Km": 1.8, "Km_unit": "mM", "Vmax": 12.3, "Vmax_unit": "μM/s", "substrate": "H2O2"}
    ],
    "pH_profile": {"optimal_pH": 4.0, "pH_range": "3.0-5.0"},
    "temperature_profile": {"optimal_temperature": 37, "temperature_range": "25-60"}
  },
  "applications": [
    {
      "application_type": "biosensing",
      "target_analyte": "H2O2",
      "detection_limit": 0.1,
      "detection_limit_unit": "μM",
      "method": "colorimetric",
      "sample_type": "serum"
    }
  ],
  "diagnostics": {
    "status": "complete",
    "confidence": 0.85,
    "warnings": []
  }
}
```

### 诊断状态说明

| 状态 | 含义 |
|------|------|
| `complete` | 提取完整，关键字段均已填充 |
| `partial` | 部分字段缺失，结果可用但不完整 |
| `failed` | 提取失败，需人工检查 |

### 常见警告

| 警告 | 含义 | 处理建议 |
|------|------|---------|
| `no_kinetics_found` | 未提取到动力学参数 | 检查 PDF 是否包含动力学数据 |
| `Km outside typical range` | Km 值超出典型范围 | 检查原文数值和单位是否正确 |
| `Analyte incompatible` | 分析物与酶类型不兼容 | 检查提取的分析物是否正确 |
| `needs_review` | 需要人工审阅 | 建议人工核对提取结果 |

---

## 常见问题

### 启动问题

**Q: 双击 start.bat 闪退**

A: 可能原因：
1. Python 未安装或不在 PATH 中 → 安装 Python 3.10+ 并勾选「Add to PATH」
2. 依赖未安装 → 打开命令行运行 `pip install -r requirements.txt`
3. 使用命令行 `python start.py` 启动可查看详细错误信息

**Q: 提示「ModuleNotFoundError」**

A: 缺少依赖包，运行：
```bash
pip install -r requirements.txt
```

**Q: 提示「tkinter not available」**

A: tkinter 通常随 Python 自带。如果缺失：
- Windows：重新运行 Python 安装程序，勾选「tcl/tk」
- Linux：`sudo apt-get install python3-tk`

### 提取问题

**Q: 预处理失败**

A: 可能原因：
1. PDF 文件损坏或加密 → 确认 PDF 可正常打开
2. PDF 路径含特殊字符 → 将 PDF 移到纯英文路径下
3. opendataloader-pdf 未安装 → `pip install opendataloader-pdf`

**Q: 提取结果为空或大部分字段缺失**

A: 可能原因：
1. PDF 不是纳米酶文献 → 系统仅支持纳米酶相关文献
2. 规则模式下提取能力有限 → 配置 API 密钥启用 AI 模式
3. PDF 文本提取不完整 → 检查预处理日志

**Q: API 调用失败**

A: 可能原因：
1. API 密钥错误 → 检查 config.yaml 中的 api_key
2. 网络问题 → 确认可访问 API 服务商的 base_url
3. 余额不足 → 检查 API 账户余额
4. 点击「测试 API」按钮验证连通性

**Q: 提取速度慢**

A: 优化建议：
1. 启用缓存（默认开启）→ 相同文件不会重复提取
2. 减少并发 → 系统默认 2 并发，API 限流时可降低
3. 关闭 VLM → 在 config.yaml 中设置 `enable_vlm: false`

### 结果问题

**Q: 酶类型提取错误**

A: 多酶活性论文中系统可能选择错误的酶类型。建议：
1. 使用 AI 模式（LLM 理解上下文更准确）
2. 检查 `diagnostics.warnings` 中的提示

**Q: Km/Vmax 单位不对**

A: 系统会自动进行单位转换和量级校验：
- M/s → μM/s（Vmax < 1.0 时自动转换）
- 超出典型范围的值会被标记为警告
- 请以原文数据为准，系统转换仅供参考

**Q: 多底物动力学数据不完整**

A: 规则模式对多底物动力学提取能力有限。建议：
1. 使用 AI 模式（LLM 可识别多底物分别的 Km/Vmax）
2. 检查 `kinetics_list` 字段（多底物数据在此处）

---

## 输出目录结构

```
project_root/
├── config.yaml              # API 配置（需手动创建）
├── start.bat                # Windows 启动脚本
├── start.py                 # Python 启动脚本
├── extraction_results/      # 默认输出目录
│   ├── paper1.json          # PDF 解析结果
│   ├── paper1_images/       # 提取的图片
│   ├── paper1_mid_task.json # 预处理中间文件
│   └── paper1_extracted.json# 最终提取结果
└── ocr_gui.log              # 运行日志
```

---

## 系统架构

```
PDF输入 → PDF解析(OpenDataLoader) → 预处理(分块/分句/分表/分图)
    → LLM结构化提取(LLM-First) → 规则提取(Fallback)
    → LLM精炼 → VLM图表提取 → 交叉验证 → 一致性修正
    → 数值校验(领域知识) → Schema验证 → 输出JSON
```

提取优先级：LLM 结构化提取 > 规则提取 > LLM 精炼 > VLM 图表提取

---

## 技术支持

如遇到问题，请提供以下信息：
1. 系统启动日志（命令行输出）
2. `ocr_gui.log` 日志文件
3. 出问题的 PDF 文件名
4. 错误截图或文本
