# llm_extractor.py - Enhanced LLM Extractor with JSON error handling
import json
import asyncio
import logging
import re
from typing import Dict, List, Optional, Any
from api_client import APIClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a nanozyme literature extraction engine. Your ONLY output is a single JSON object — nothing else.

HARD RULES:
1. Output exactly ONE JSON object. No text before or after it.
2. No Markdown fences (```json ... ```), no comments, no explanations.
3. Only extract information explicitly stated in the source text. If the text does not say it, do not output it.
4. Use null for missing or uncertain values. Never guess or fabricate data.
5. Preserve original evidence text or reference clues whenever possible.

OUTPUT STRUCTURE — your JSON MUST have these 5 top-level keys (use empty object/array if nothing to extract):
{
  "paper": {},
  "nanozyme_systems": [],
  "catalytic_activities": [],
  "applications": [],
  "evidence": []
}

FIELD BOUNDARY RULES — obey these or the downstream pipeline WILL break:

A. substrate vs target_analyte
   - substrate: the molecule consumed in the catalytic reaction (e.g., TMB, ABTS, H2O2, OPD, DCFH-DA).
   - target_analyte: the molecule or species being detected/quantified in an application (e.g., glucose, dopamine, Hg2+, cancer cells).
   - NEVER put a target_analyte into substrates. If something is being sensed/detected, it goes in applications.target_analyte, NOT in catalytic_activities.substrates.

B. material_name_raw vs composition
   - material_name_raw: the name used in the paper for the material (e.g., "Fe3O4@C", "R-MnCo2O4", "Au@Ag core-shell nanoparticles").
   - composition: individual chemical components only (e.g., ["Fe3O4", "C"] or ["Mn", "Co", "O4"]). NOT the full material name.

C. activity vs application
   - activity (enzyme_like_type): what catalytic property the material has (e.g., peroxidase-like, oxidase-like).
   - application: what task that catalytic property is used for (e.g., glucose detection, wound healing, pollutant degradation).
   - An activity is NOT an application. "peroxidase-like activity" is an activity; "glucose biosensor" is an application.

D. evidence
   - Every kinetic parameter, application claim, and key material property MUST include an evidence reference.
   - Use evidence_refs with sentence_id from the input text (e.g., "S0001").
   - For kinetics especially, include the original text snippet as evidence_text when possible.

KINETICS OUTPUT FORMAT:
{
  "parameter": "Km" or "Vmax" or "kcat" or "kcat/Km",
  "value": <number>,
  "unit": "mM" or "M" or "s-1" or "mM/s" etc.,
  "substrate": "<the substrate this parameter was measured with>",
  "evidence_refs": ["<sentence_id>"],
  "evidence_text": "<original text snippet>"
}
- Only output a kinetics entry if the paper gives an explicit numeric value. Do NOT create entries with value=null.
- Always specify which substrate the kinetic parameter was measured for.
- Include evidence_text: the original sentence or phrase containing the value.

REMEMBER: You are producing a CANDIDATE structure for downstream normalization. Focus on accuracy and evidence. Leave deduplication, canonical ID assignment, and schema normalization to the integrator."""


class JSONFixer:
    """JSON format fixer for common LLM output issues"""

    @staticmethod
    def fix_common_issues(text: str) -> Optional[Dict]:
        if not text:
            return None

        text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
        text = text.strip()

        strategies = [
            JSONFixer._fix_single_quotes,
            JSONFixer._fix_trailing_comma,
            JSONFixer._fix_unquoted_keys,
            JSONFixer._fix_truncated_json,
            JSONFixer._fix_control_characters,
        ]

        for strategy in strategies:
            text = strategy(text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            text = JSONFixer._aggressive_fix(text)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _fix_single_quotes(text: str) -> str:
        result = []
        i = 0
        in_string = False
        current_quote = None

        while i < len(text):
            char = text[i]
            if not in_string and char in ('"', "'"):
                in_string = True
                current_quote = char
                result.append('"')
            elif in_string and char == current_quote:
                if i > 0 and text[i-1] == '\\':
                    result.append(char)
                else:
                    in_string = False
                    result.append('"')
            elif in_string and char == "'" and current_quote == "'":
                result.append('"')
            else:
                result.append(char)
            i += 1
        return ''.join(result)

    @staticmethod
    def _fix_trailing_comma(text: str) -> str:
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        return text

    @staticmethod
    def _fix_unquoted_keys(text: str) -> str:
        def replace_key(match):
            key = match.group(1)
            return f'"{key}"'
        text = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', replace_key, text)
        return text

    @staticmethod
    def _fix_truncated_json(text: str) -> Optional[str]:
        stack = []
        in_string = False
        escape_next = False

        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char in '{[':
                stack.append(char)
            elif char == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
            elif char == ']':
                if stack and stack[-1] == '[':
                    stack.pop()

        if stack:
            closes = {'{': '}', '[': ']'}
            result = text
            for opener in reversed(stack):
                result += closes[opener]
            return result
        return text

    @staticmethod
    def _fix_control_characters(text: str) -> str:
        text = re.sub(r'[\x00-\x09\x0b\x0c\x0e-\x1f\x7f]', '', text)
        return text

    @staticmethod
    def _aggressive_fix(text: str) -> str:
        first_brace = text.find('{')
        first_bracket = text.find('[')

        start = 0
        if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
            start = first_brace
        elif first_bracket != -1:
            start = first_bracket

        if start > 0:
            text = text[start:]

        text = JSONFixer._fix_truncated_json(text) or text

        last_brace = text.rfind('}')
        last_bracket = text.rfind(']')

        end = len(text)
        if last_brace != -1 and (last_bracket == -1 or last_brace > last_bracket):
            end = last_brace + 1
        elif last_bracket != -1:
            end = last_bracket + 1

        return text[:end]


_REQUIRED_TOP_KEYS = {"paper", "nanozyme_systems", "catalytic_activities", "applications", "evidence"}


class LLMExtractor:
    """Enhanced LLM Extractor"""

    def __init__(self, client: APIClient, batch_size: int = 5):
        self.client = client
        self.batch_size = batch_size
        self.json_fixer = JSONFixer()

    @staticmethod
    def _ensure_candidate_structure(result: Dict) -> Dict:
        if not isinstance(result, dict):
            return result
        for key in _REQUIRED_TOP_KEYS:
            if key not in result:
                if key == "paper":
                    result[key] = {}
                else:
                    result[key] = []
        return result

    async def extract_single_chunk(
        self,
        chunk: str,
        prompt_template: str,
        chunk_index: int = 0,
        total_chunks: int = 1
    ) -> Optional[Dict]:
        chunk_label = f"Chunk {chunk_index}/{total_chunks}"
        try:
            logger.info("=" * 60)
            logger.info(f"[LLM] 开始处理 {chunk_label}")
            logger.info(f"[LLM] 输入文本块长度: {len(chunk)} 字符")
            chunk_preview = chunk[:300].replace('\n', ' ') if chunk else '(空)'
            logger.info(
                f"[LLM] 文本块内容预览: {chunk_preview}"
                f"{'...' if len(chunk) > 300 else ''}"
            )

            user_prompt = prompt_template.replace("{text}", chunk)

            system_prompt = _SYSTEM_PROMPT

            logger.info(f"[LLM] System Prompt 长度: {len(system_prompt)} 字符")
            logger.info(f"[LLM] User Prompt 长度: {len(user_prompt)} 字符")
            logger.info("[LLM] ---- User Prompt 开始 ----")
            for line in user_prompt.splitlines():
                logger.info(f"[LLM]   {line}")
            logger.info("[LLM] ---- User Prompt 结束 ----")

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            logger.info(f"[LLM] 正在调用 API (temperature=0.1, max_tokens=8192)...")
            response = await self.client.chat_completion_text(
                messages,
                temperature=0.1,
                max_tokens=8192
            )

            if not response:
                logger.warning(f"[LLM] {chunk_label}: API 返回空响应")
                return None

            logger.info(f"[LLM] API 响应长度: {len(response)} 字符")
            logger.info("[LLM] ---- API 原始响应 ----")
            for line in response.splitlines():
                logger.info(f"[LLM]   {line}")
            logger.info("[LLM] ---- 原始响应结束 ----")

            result = self._robust_json_parse(response)
            if result:
                result = self._ensure_candidate_structure(result)
                logger.info(
                    f"[LLM] {chunk_label} JSON 解析成功，"
                    f"提取到字段: {list(result.keys())}"
                )
                return result

            start = response.find('{')
            if start != -1:
                logger.warning(f"[LLM] {chunk_label} 发现 JSON 边界但解析失败")

            logger.warning(
                f"[LLM] {chunk_label} JSON 解析失败，"
                f"原始响应前200字: {response[:200]}..."
            )
            return {
                "error": "non_json_response",
                "raw_preview": response[:500],
                "_chunk_index": chunk_index
            }

        except Exception as e:
            logger.error(f"[LLM] {chunk_label} 处理异常: {e}")
            raise

    async def extract_all_chunks(
        self,
        chunks: List[str],
        prompt_template: str
    ) -> List[Dict]:
        logger.info("=" * 60)
        logger.info(f"[LLM] extract_all_chunks 启动，共 {len(chunks)} 个文本块")
        logger.info(f"[LLM] 批处理大小: {self.batch_size}")
        logger.info(f"[LLM] 提示词模板长度: {len(prompt_template)} 字符")
        template_preview = prompt_template[:400].replace('\n', ' ')
        logger.info(f"[LLM] 提示词模板预览: {template_preview}{'...' if len(prompt_template) > 400 else ''}")
        logger.info("=" * 60)

        if len(chunks) == 1:
            logger.info("[LLM] 单块模式，直接串行处理")
            result = await self.extract_single_chunk(
                chunks[0], prompt_template, chunk_index=1, total_chunks=1
            )
            return [result] if result else []

        semaphore = asyncio.Semaphore(self.batch_size)
        processed = 0
        processed_lock = asyncio.Lock()

        async def bounded(chunk: str, idx: int):
            nonlocal processed
            async with semaphore:
                try:
                    result = await self.extract_single_chunk(
                        chunk, prompt_template,
                        chunk_index=idx, total_chunks=len(chunks)
                    )
                    async with processed_lock:
                        processed += 1
                        if processed % 5 == 0 or processed == len(chunks):
                            logger.info(
                                f"[LLM] 整体进度: {processed}/{len(chunks)} 块已完成"
                            )
                    return result
                except Exception as e:
                    logger.error(f"[LLM] Chunk {idx} 处理错误: {e}")
                    return None

        tasks = [bounded(c, i + 1) for i, c in enumerate(chunks)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid = []
        non_json_count = 0
        error_count = 0
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"[LLM] Chunk {i+1} 执行异常: {r}")
                error_count += 1
            elif r and isinstance(r, dict) and r.get("error") == "non_json_response":
                logger.warning(f"[LLM] Chunk {i+1} 返回非 JSON 响应，已记录")
                non_json_count += 1
            elif r and isinstance(r, dict) and "error" in r:
                logger.warning(f"[LLM] Chunk {i+1} 返回错误响应: {r.get('error')}")
                error_count += 1
            elif r:
                valid.append(r)

        logger.info(
            f"[LLM] 全部完成: {len(valid)}/{len(chunks)} 块成功提取，"
            f"non_json_response: {non_json_count}，其他异常: {error_count}"
        )
        return valid

    def _robust_json_parse(self, text: str) -> Optional[Dict]:
        if not text:
            return None

        _KEY_NORMALIZE_MAP = {"pH": "ph", "PH": "ph"}

        def _merge_pairs(pairs):
            d = {}
            for key, value in pairs:
                norm_key = _KEY_NORMALIZE_MAP.get(key, key)
                if norm_key in d:
                    if isinstance(d[norm_key], list) and not isinstance(value, list):
                        d[norm_key].append(value)
                    elif isinstance(value, list) and not isinstance(d[norm_key], list):
                        d[norm_key] = [d[norm_key]] + value
                    else:
                        d[norm_key] = value
                else:
                    d[norm_key] = value
            return d

        try:
            return json.loads(text.strip(), object_pairs_hook=_merge_pairs)
        except json.JSONDecodeError:
            pass

        code_patterns = [
            r'```json\s*([\s\S]*?)\s*```',
            r'```\s*([\s\S]*?)\s*```',
        ]
        for pattern in code_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue

        start = text.find('{')
        if start != -1:
            brace_count = 0
            in_string = False
            escape = False
            for i in range(start, len(text)):
                char = text[i]
                if escape:
                    escape = False
                    continue
                if char == '\\':
                    escape = True
                    continue
                if char == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_candidate = text[start:i+1]
                        try:
                            return json.loads(json_candidate)
                        except json.JSONDecodeError:
                            fixed = self.json_fixer.fix_common_issues(json_candidate)
                            if fixed:
                                return fixed
                        break

        fixed = self.json_fixer.fix_common_issues(text)
        if fixed:
            return fixed

        cleaned = re.sub(r'[^\{\}\[\]\,\:\"\'\w\.\-\s]', '', text)
        try:
            return json.loads(cleaned)
        except:
            pass

        return None


# ============================================================
# TableExtractor：专用于表格结构化数据提取
# ============================================================

_TABLE_SYSTEM_PROMPT = """\
You are extracting structured nanozyme data from parsed scientific tables.
Do NOT summarize. Extract row-level records exactly as they appear.
Preserve units exactly. If a value is missing, use null.
Do not infer values not present in the table.
Every record must include source_table_id and source_page.

For multi-material tables: output one record per material row.
For multi-substrate kinetics tables: output one record per material+substrate combination.
For SI tables: be conservative — preserve null for absent values.

Return strict JSON only (no markdown fences, no commentary):
{
  "records": [
    {
      "record_type": "kinetics_parameters",
      "material": null,
      "enzyme_like_activity": null,
      "substrate": null,
      "Km_value": null,
      "Km_unit": null,
      "Vmax_value": null,
      "Vmax_unit": null,
      "kcat_value": null,
      "kcat_unit": null,
      "specific_activity_value": null,
      "specific_activity_unit": null,
      "assay_condition": {
        "pH": null,
        "temperature": null,
        "buffer": null,
        "H2O2_concentration": null,
        "TMB_concentration": null
      },
      "other_parameters": {},
      "source_table_id": "table_001",
      "source_page": 1,
      "evidence_text": ""
    }
  ],
  "warnings": []
}"""

_TABLE_USER_TEMPLATE = """\
Table ID: {table_id}
Table Type: {table_type}
Page: {page}
Caption: {caption}

Table Content:
{content}

Extract all data records from this table. Return strict JSON."""


class TableExtractor:
    """
    TableExtractor：独立的表格结构化数据提取器。
    使用 LLM 对表格进行逐行抽取，支持多种表格类型。
    """

    def __init__(self, client: APIClient, batch_size: int = 3):
        self.client = client
        self.batch_size = batch_size
        self.json_fixer = JSONFixer()

    async def extract_single_table(
        self,
        table: Dict[str, Any],
        table_index: int = 0,
        total_tables: int = 1,
    ) -> Dict[str, Any]:
        """提取单个表格"""
        table_id = table.get("table_id", f"table_{table_index:03d}")
        table_type = table.get("table_type", "general_table")
        page = table.get("page", 1)
        caption = table.get("caption", "")

        # 优先使用 markdown 格式，其次 content_text
        content = table.get("markdown") or table.get("content_text") or ""
        if not content.strip():
            logger.warning(f"[Table] {table_id}: 内容为空，跳过")
            return {
                "table_id": table_id,
                "records": [],
                "warnings": ["empty_content"],
                "error": None,
            }

        user_prompt = _TABLE_USER_TEMPLATE.format(
            table_id=table_id,
            table_type=table_type,
            page=page,
            caption=caption or "(no caption)",
            content=content[:3000],  # 防止超长表格
        )

        try:
            logger.info(f"[Table] 提取 {table_id} (type={table_type}, page={page})")
            messages = [
                {"role": "system", "content": _TABLE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
            raw_text = await self.client.chat_completion_text(
                messages,
                temperature=0.1,
                max_tokens=8192,
            )
            if not raw_text:
                return {
                    "table_id": table_id,
                    "records": [],
                    "warnings": ["empty_api_response"],
                    "error": "empty_response",
                }

            parsed = self._parse_table_response(raw_text, table_id)
            parsed["table_id"] = table_id
            parsed["table_type"] = table_type
            parsed["source_page"] = page
            parsed["caption"] = caption
            return parsed

        except Exception as e:
            logger.error(f"[Table] {table_id} 提取失败: {e}")
            return {
                "table_id": table_id,
                "records": [],
                "warnings": [],
                "error": str(e),
            }

    async def extract_all_tables(
        self,
        table_extraction_task: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        提取 table_extraction_task 中所有表格。
        如果 task 为空或不存在，返回空列表（不报错）。
        """
        if not table_extraction_task:
            logger.info("[Table] table_extraction_task 为空，跳过表格提取")
            return []

        tables = table_extraction_task.get("tables", [])
        if not tables:
            logger.info("[Table] table_extraction_task.tables 为空，跳过表格提取")
            return []

        logger.info(f"[Table] 开始提取 {len(tables)} 个表格")
        sem = asyncio.Semaphore(self.batch_size)

        async def bounded(table: Dict[str, Any], idx: int) -> Dict[str, Any]:
            async with sem:
                return await self.extract_single_table(table, idx, len(tables))

        tasks = [bounded(t, i + 1) for i, t in enumerate(tables)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid: List[Dict[str, Any]] = []
        error_count = 0
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"[Table] 表格 {i+1} 执行异常: {r}")
                error_count += 1
                valid.append({
                    "table_id": tables[i].get("table_id", f"table_{i+1:03d}"),
                    "records": [],
                    "warnings": [],
                    "error": str(r),
                })
            elif isinstance(r, dict):
                valid.append(r)

        success = sum(1 for r in valid if not r.get("error"))
        logger.info(f"[Table] 表格提取完成: {success}/{len(tables)} 成功, {error_count} 异常")
        return valid

    def _parse_table_response(self, text: str, table_id: str = "") -> Dict[str, Any]:
        """解析 LLM 返回的表格 JSON"""
        if not text:
            return {"records": [], "warnings": ["empty_response"]}

        # 去除 markdown 包裹
        text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
        text = text.strip()

        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                records = obj.get("records", [])
                if not isinstance(records, list):
                    records = []
                return {
                    "records": records,
                    "warnings": obj.get("warnings", []),
                }
        except json.JSONDecodeError:
            pass

        # 尝试 JSONFixer
        fixed = self.json_fixer.fix_common_issues(text)
        if fixed and isinstance(fixed, dict):
            return {
                "records": fixed.get("records", []),
                "warnings": fixed.get("warnings", ["json_repaired"]),
            }

        logger.warning(f"[Table] {table_id}: JSON 解析失败，返回空记录")
        return {"records": [], "warnings": ["json_parse_failed"]}
