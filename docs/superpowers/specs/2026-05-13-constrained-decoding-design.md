# 约束解码引擎设计文档

## 概述

基于研究报告《AI/LLM驱动的科学文献提取前沿与系统演进》的核心差距分析，实现多层约束解码策略，将JSON输出结构合规率从~92%提升到>99%。

## 背景

### 当前问题

| 层级 | 当前实现 | 问题 |
|------|---------|------|
| `llm_structured_extractor.py` | instructor库 + `response_format: {type: "json_object"}` | instructor依赖OpenAI客户端，对DeepSeek/国产模型兼容性差；json_object仅保证JSON格式，不保证Schema合规 |
| `llm_extractor.py` | 无任何约束，纯文本解析 | 完全依赖后置JSON修复 |
| `schema_constraints.py` | `get_schema_for_openai()` 已定义JSON Schema | 未被任何调用点使用 |
| `api_client.py` | `chat_completion_text` 支持 `extra_params` | 可传入 `response_format` 但当前未传入 |

### 目标

- JSON结构合规率：~92% → >99%
- 减少Pydantic验证失败导致的重试开销
- 兼容DeepSeek/GLM/Qwen等国产模型
- 不破坏现有功能

## 设计方案：多层约束策略

### 架构

```
调用方（llm_structured_extractor / llm_extractor / extraction_agents）
    ↓
ConstrainedDecodingEngine.call(messages, schema, task_name)
    ↓
┌─────────────────────────────────────────────┐
│ 第1层：API原生 json_schema 约束              │
│   检测模型是否支持 → 支持：直接传入           │
│   不支持 → 降级到第2层                       │
├─────────────────────────────────────────────┤
│ 第2层：json_object 模式 + Schema Prompt注入  │
│   在system prompt中嵌入完整Schema描述         │
│   + 枚举值约束 + 字段类型说明                │
├─────────────────────────────────────────────┤
│ 第3层：Pydantic后验证 + auto_fix              │
│   解析JSON → Pydantic校验 → 自动修复         │
│   修复失败 → 标记diagnostics                 │
├─────────────────────────────────────────────┤
│ 第4层：Schema感知Prompt增强（贯穿1-3层）      │
│   在prompt中明确列出：                        │
│   - enzyme_like_type 枚举值                   │
│   - application_type 枚举值                   │
│   - 数值范围约束                              │
│   - 必填字段说明                              │
└─────────────────────────────────────────────┘
```

### 核心组件

#### 1. ConstrainedDecodingEngine（新增 `constrained_decoding.py`）

```python
class ConstrainedDecodingEngine:
    def __init__(self, client: APIClient, config=None):
        self.client = client
        self.model = client.llm_model
        self.supports_json_schema = self._detect_json_schema_support()
    
    async def call(
        self,
        messages: List[Dict],
        task_name: str,
        schema: Optional[Dict] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Optional[Dict[str, Any]]:
        # 1. Schema感知Prompt增强
        enhanced_messages = self._inject_schema_prompt(messages, task_name, schema)
        
        # 2. 选择约束层级
        if self.supports_json_schema and schema:
            result = await self._call_with_json_schema(enhanced_messages, schema, temperature, max_tokens)
        else:
            result = await self._call_with_json_object(enhanced_messages, temperature, max_tokens)
        
        # 3. 后验证 + 自动修复
        if result and schema:
            result = self._validate_and_fix(result, schema, task_name)
        
        return result
```

#### 2. 模型能力检测

```python
SUPPORTED_JSON_SCHEMA_PREFIXES = [
    "gpt-4o", "gpt-4-turbo",
    "deepseek-chat", "deepseek-reasoner",
    "glm-4", "glm-4-plus",
]

def _detect_json_schema_support(self) -> bool:
    model = self.model.lower()
    return any(model.startswith(prefix) for prefix in SUPPORTED_JSON_SCHEMA_PREFIXES)
```

#### 2.1 API调用参数

- `_call_with_json_schema`: 传入 `response_format={"type": "json_schema", "json_schema": {"name": task_name, "strict": True, "schema": schema}}`
- `_call_with_json_object`: 传入 `response_format={"type": "json_object"}`
- 两种模式均通过 `api_client.chat_completion_text` 的 `extra_params` 参数透传

#### 3. Schema感知Prompt增强

在每条LLM调用的system prompt中自动追加约束说明：

```python
SCHEMA_CONSTRAINT_PROMPT = """
<schema_constraints>
Output a JSON object strictly conforming to this schema:
- enzyme_like_type: must be one of [{enzyme_enum}]
- application_type: must be one of [{app_enum}]
- All numeric fields (Km, Vmax, kcat, etc.) must be numbers or null, never strings
- size must be paired with size_unit; Km with Km_unit; Vmax with Vmax_unit
- Required fields: {required_fields}
- Do NOT include any fields not in the schema
</schema_constraints>
"""
```

### Schema完善

#### 主Schema改进

1. 补全 `additionalProperties: false` 到所有object节点
2. 补全 `required` 字段定义
3. 为 `enzyme_like_type` 和 `application_type` 添加 `enum` 约束
4. 为数值字段添加 `minimum`/`maximum` 约束提示

#### 子任务Schema注册表

| Schema名 | 用途 | 关键约束 |
|----------|------|---------|
| `KINETICS_SCHEMA` | 动力学提取 | Km/Vmax数值+单位、substrate必填 |
| `MORPHOLOGY_SCHEMA` | 形态提取 | size+size_unit配对 |
| `APPLICATION_SCHEMA` | 应用提取 | application_type枚举约束 |
| `ENZYME_TYPE_SCHEMA` | 酶类型提取 | enzyme_like_type枚举约束 |
| `SYNTHESIS_SCHEMA` | 合成提取 | precursors数组 |
| `PH_TEMP_SCHEMA` | pH/温度提取 | optimal_pH/optimal_temperature数值范围 |
| `NANOZYME_EXTRACTION_SCHEMA` | 全量提取 | 完整Schema |

```python
TASK_SCHEMAS = {
    "kinetics": KINETICS_SCHEMA,
    "morphology": MORPHOLOGY_SCHEMA,
    "applications": APPLICATION_SCHEMA,
    "enzyme_type": ENZYME_TYPE_SCHEMA,
    "synthesis": SYNTHESIS_SCHEMA,
    "ph_temp": PH_TEMP_SCHEMA,
    "table_kinetics": KINETICS_SCHEMA,
    "full_extraction": NANOZYME_EXTRACTION_SCHEMA,
}
```

### 后验证与自动修复增强

#### 增强修复规则

| 错误类型 | 修复策略 |
|---------|---------|
| enzyme_like_type 不在枚举中 | 调用 `nanozyme_models.normalize_canonical()` 归一化 |
| application_type 不在枚举中 | 调用 `get_application_type_enum_string()` 归一化 |
| 数值字段为字符串 | 尝试 `float()` 转换，失败则置null |
| size无size_unit | 置null并标记warning |
| Km无Km_unit | 置null并标记warning |
| 未知字段 | 移除 |
| required字段缺失 | 填充默认值（name=""等） |

#### 修复后二次验证

修复后重新运行 `validate_against_schema`，若仍有错误则标记到 `diagnostics` 而非丢弃结果。

## 改动文件清单

| 文件 | 改动类型 | 改动内容 |
|------|---------|---------|
| `constrained_decoding.py` | 新增 | ConstrainedDecodingEngine核心实现 |
| `schema_constraints.py` | 修改 | 完善主Schema；新增6个子任务Schema；新增TASK_SCHEMAS注册表 |
| `api_client.py` | 修改 | `chat_completion_text` 增加response_format参数透传；新增 `supports_json_schema()` 检测方法 |
| `llm_structured_extractor.py` | 修改 | 移除instructor依赖路径；使用ConstrainedDecodingEngine统一调用 |
| `llm_extractor.py` | 修改 | 全文提取启用约束解码（json_object + Schema Prompt注入） |
| `extraction_agents.py` | 修改 | 4个Agent使用ConstrainedDecodingEngine |

## 不改动内容

- `extraction_prompts.py`：现有prompt模板不变，Schema约束通过ConstrainedDecodingEngine追加
- `nanozyme_preprocessor_midjson.py`：预处理层不受影响
- `cross_validation_agent.py`：交叉验证逻辑不变
- `consistency_agent.py`：一致性修正逻辑不变
- `numeric_validator.py`：数值校验逻辑不变
- `vlm_extractor.py`：VLM提取暂不纳入约束解码（VLM输出为自由文本描述，不适合JSON Schema约束）
- `nanozyme_models.py`：枚举定义不变

## 验证方式

1. 单元测试：`tests/test_constrained_decoding.py`
   - 测试模型能力检测
   - 测试Schema Prompt注入
   - 测试后验证与自动修复
   - 测试降级策略
2. 集成测试：使用真实PDF运行全流程，对比约束解码前后的结构合规率
3. 回归测试：确保现有测试全部通过

## 风险与后续

- 部分国产模型可能不支持 `json_schema`，需要充分测试降级路径
- Schema定义需要严格符合OpenAI JSON Schema规范，否则API调用会失败
- 后续可扩展：将VLM提取也纳入约束解码（需要设计VLM专用的输出Schema）
- 后续可扩展：引入领域微调（阶段一原计划的第二部分）
