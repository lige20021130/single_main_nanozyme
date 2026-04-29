# vlm_extractor.py - 增强版：统一日志、进度回调
import base64
import json
import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable
from api_client import APIClient
from nanozyme_models import EnzymeType, get_figure_type_enum_string, get_enzyme_type_enum_string, get_application_type_enum_string

logger = logging.getLogger(__name__)

VISION_PROMPT = """请分析这张来自纳米酶论文的图像。

你需要完成：
1. 判断图像类型
2. 判断它与哪个材料 system 或 catalytic activity 相关
3. 提取图中明确可读的重要数值或标签
4. 生成简洁 observations
5. 如果图像只是表征图，也要提取与材料结构有关的信息
6. 如果图中文字不清晰，不要猜测

输出要求：
- 只能输出一个 JSON 对象
- 不要输出 Markdown
- 不要输出解释
- 不要臆测数值

输出格式：
{
  "figure_type": null,
  "linked_material_mentions": [],
  "linked_activity_type": null,
  "extracted_values": {
    "Km": [{"value": null, "unit": "mM", "material": null}],
    "Vmax": [{"value": null, "unit": null, "material": null}],
    "particle_size": {"value": null, "unit": "nm"},
    "peak_positions": [],
    "other_values": [],
    "sensing_performance": {{"LOD": null, "linear_range": null, "sensitivity": null}},
    "application_hints": []
  },
  "observations": [],
  "evidence_refs": [],
  "reliability_note": null
}

注意：
- Km 和 Vmax 均为列表格式。如果图中有多个材料/体系的动力学参数，每条分开列出，并在 material 字段填写对应材料标签（如图例中的名称）。
- 如果图中只有一个体系的参数，列表只有一条，material 可为 null。
- 如果图中无法读出参数值，列表为空 []。

规则：
- figure_type 只能使用以下枚举之一：
  {{figure_type_enum}}

- linked_activity_type 只能使用以下枚举之一：
  {{enzyme_type_enum}},
  null

- application_hints: if the figure or caption suggests an application scenario (e.g., glucose sensing, tumor therapy, pollutant degradation), list the application type keywords. Allowed values: {application_type_enum}

- 只有当图中数值明确可读时，才填写 Km / Vmax / particle_size
- 如果 caption 提供了高质量上下文，可以用于辅助理解图像类型
- 如果图中只有结构示意，不要伪造数值
- **重要**：判断 linked_activity_type 时，必须严格结合正文或图注的辅助上下文。如果上下文中明确指出这是 oxidase-like 活性，请勿仅因看到 TMB 就盲目猜测 peroxidase-like。优先与文本的定性描述保持一致！
{{additional_context}}

图注如下：
{{caption}}"""

class VLMExtractor:
    _CAPTION_TYPE_HINTS = {
        "kinetics_caption": "此图很可能是动力学曲线（如 Michaelis-Menten / Lineweaver-Burk），请重点提取 Km、Vmax、kcat 等参数值和对应材料标签。",
        "application_caption": "此图很可能是应用性能图（如检测校准曲线），请重点提取 LOD、linear_range、sensitivity 等传感性能参数。",
        "mechanism_caption": "此图很可能是机制示意图，请重点描述反应路径、中间体、ROS 生成机制等，不需要提取动力学数值。",
        "comparison_caption": "此图很可能是性能对比图，请重点提取不同材料的性能对比数值。",
        "morphology_caption": "此图很可能是形貌表征图（SEM/TEM），请重点提取粒径、形貌、结构信息，不需要提取动力学或传感参数。",
    }

    def __init__(self, client: APIClient, batch_size: int = 2):
        self.client = client
        self.batch_size = batch_size

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    async def _extract_from_image(self, image_path: str, caption: str = "", description: str = "", elem_type: str = "image", vlm_reason: str = "", caption_type: str = "", body_context: str = "") -> Dict:
        if not Path(image_path).exists():
            logger.warning(f"图片不存在: {image_path}")
            return {"error": "file_not_found"}

        b64 = self._encode_image(image_path)

        context_parts = []
        if caption:
            context_parts.append(f"图注：{caption}")
        if description:
            context_parts.append(f"解析层图片描述：{description}")
        if elem_type and elem_type != "image":
            context_parts.append(f"元素类型：{elem_type}")
        if vlm_reason:
            context_parts.append(f"进入 VLM 原因：{vlm_reason}")

        if caption_type and caption_type in self._CAPTION_TYPE_HINTS:
            context_parts.append(self._CAPTION_TYPE_HINTS[caption_type])

        # Inject body_context: sentences from paper body that reference or co-occur with this figure.
        # This helps VLM distinguish activity types (e.g. oxidase-like vs peroxidase-like) from
        # experimental descriptions rather than visual appearance alone.
        if body_context:
            context_parts.append(f"正文相关句（辅助判断图表类型，不作为数值来源）：{body_context[:400]}")

        additional_context = ""
        if context_parts:
            lines = ["\n辅助上下文："] + context_parts + [
                "\n注意：description 等辅助上下文仅用于帮助理解图像背景，不可替代图内可见证据，不可据此臆造数值。"
            ]
            additional_context = "\n".join(lines)


        prompt = VISION_PROMPT.replace("{{caption}}", caption or "无图注")
        prompt = prompt.replace("{{additional_context}}", additional_context)
        prompt = prompt.replace("{{figure_type_enum}}", get_figure_type_enum_string())
        prompt = prompt.replace("{{enzyme_type_enum}}", get_enzyme_type_enum_string())
        prompt = prompt.replace("{application_type_enum}", get_application_type_enum_string())

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        }]

        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                response = await self.client.chat_completion_vision(messages)

                if not response:
                    return {"error": "empty_response"}

                try:
                    return json.loads(response)
                except json.JSONDecodeError:
                    json_match = re.search(r'\{[\s\S]*\}', response)
                    if json_match:
                        try:
                            return json.loads(json_match.group(0))
                        except:
                            pass
                    return {"error": "json_parse_failed", "raw": response}

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"VLM 请求异常 (attempt {attempt + 1}/{max_retries}), {wait}s 后重试: {e}")
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"VLM 请求异常: 重试 {max_retries} 次后仍失败: {e}")
                return {"error": str(e)}

    async def extract_all_images(self, vlm_tasks: List[Dict]) -> List[Dict]:
        logger.info(f"开始处理 {len(vlm_tasks)} 个图像任务, 批处理大小: {self.batch_size}")
        semaphore = asyncio.Semaphore(self.batch_size)
        processed = 0

        async def bounded(task):
            nonlocal processed
            async with semaphore:
                try:
                    image_path = task.get('image_path', '未知')
                    logger.debug(f"处理图像: {Path(image_path).name}")
                    result = await self._extract_from_image(
                        task['image_path'],
                        caption=task.get('caption', ''),
                        description=task.get('description', ''),
                        elem_type=task.get('elem_type', 'image'),
                        vlm_reason=task.get('vlm_reason', ''),
                        caption_type=task.get('caption_type', ''),
                        body_context=task.get('body_context', ''),
                    )
                except Exception as e:
                    logger.error(f"VLM 任务执行异常 ({task.get('image_path', '未知')}): {e}")
                    result = {"error": str(e)}
                processed += 1
                if processed % 3 == 0 or processed == len(vlm_tasks):
                    logger.info(f"VLM 进度: {processed}/{len(vlm_tasks)} 张图片")
                return (result, task)

        tasks = [bounded(t) for t in vlm_tasks]
        # 收集元组结果
        raw_results = await asyncio.gather(*tasks)

        final_results = []
        for res, src_task in raw_results:
            if isinstance(res, dict):
                res['_source'] = src_task
            else:
                res = {"error": "unknown_error", "_source": src_task}
            final_results.append(res)

        success_count = sum(1 for r in final_results if isinstance(r, dict) and 'error' not in r)
        error_count = len(final_results) - success_count
        logger.info(f"VLM 提取完成: 总任务 {len(vlm_tasks)}, 成功 {success_count}, 错误 {error_count}")

        return final_results
