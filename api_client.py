# api_client.py - 支持速率限制处理的API客户端
"""
纳米酶文献提取系统 - API客户端

增强功能：
1. 支持速率限制处理（429错误自动重试）
2. 指数退避重试机制
3. 请求限流（令牌桶算法）
4. 并发控制
"""

import asyncio
import logging
import time
import json
import random
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import threading

import aiohttp

logger = logging.getLogger(__name__)

try:
    from config_manager import ConfigManager
    CONFIG_MANAGER_AVAILABLE = True
except ImportError:
    CONFIG_MANAGER_AVAILABLE = False


def _to_config_dict(config: Any) -> Dict[str, Any]:
    if not config:
        return {}
    if isinstance(config, dict):
        return dict(config)
    if hasattr(config, "to_dict"):
        return config.to_dict()
    if hasattr(config, "__dict__"):
        return dict(config.__dict__)
    return {}


@dataclass
class RateLimitConfig:
    """速率限制配置"""
    requests_per_minute: int = 60  # 每分钟请求数
    requests_per_second: int = 10   # 每秒请求数
    max_retries: int = 5            # 最大重试次数
    base_delay: float = 1.0        # 基础延迟(秒)
    max_delay: float = 60.0       # 最大延迟(秒)
    retry_on_429: bool = True     # 遇到429是否重试
    respect_retry_after: bool = True  # 是否遵守Retry-After头


class TokenBucket:
    """令牌桶算法实现"""
    
    def __init__(self, rate: float, capacity: float):
        self.rate = rate  # 每秒补充的令牌数
        self.capacity = capacity  # 桶容量
        self.tokens = capacity
        self.last_update = time.time()
        self._lock = threading.Lock()
    
    def consume(self, tokens: float = 1.0) -> float:
        """
        尝试消费令牌
        
        Returns:
            需要等待的秒数，如果可以立即消费则返回0
        """
        with self._lock:
            now = time.time()
            # 补充令牌
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0
            else:
                # 需要等待的时间
                wait_time = (tokens - self.tokens) / self.rate
                return wait_time
    
    async def async_consume(self, tokens: float = 1.0) -> float:
        """异步版本的令牌消费"""
        total_wait = 0.0
        while True:
            wait_time = self.consume(tokens)
            if wait_time <= 0:
                return total_wait
            total_wait += wait_time
            await asyncio.sleep(wait_time)


class APIClient:
    """
    API客户端
    
    支持：
    - LLM文本补全
    - VLM图像分析
    - 速率限制处理
    - 自动重试
    """
    
    def __init__(
        self,
        llm_base_url: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_model: Optional[str] = None,
        vlm_base_url: Optional[str] = None,
        vlm_api_key: Optional[str] = None,
        vlm_model: Optional[str] = None,
        rate_limit_config: Optional[RateLimitConfig] = None
    ):
        # 加载配置
        self._load_config()

        managed_config = self._load_managed_config()
        if managed_config:
            _llm_cfg = _to_config_dict(managed_config.llm)
            _vlm_cfg = _to_config_dict(managed_config.vlm)
            _rate_limit_cfg = _to_config_dict(managed_config.rate_limit)
        else:
            _providers = self.config.get('providers', {})
            _llm_cfg = _providers.get('llm') or self.config.get('text_llm', {})
            _vlm_cfg = _providers.get('vlm') or self.config.get('vision_vlm', {})
            _rate_limit_cfg = self.config.get('rate_limit', {})

        # LLM配置
        self.llm_base_url = llm_base_url or _llm_cfg.get('base_url', '')
        self.llm_api_key = llm_api_key or _llm_cfg.get('api_key', '')
        self.llm_model = llm_model or _llm_cfg.get('model', 'glm-4')

        # VLM配置
        self.vlm_base_url = vlm_base_url or _vlm_cfg.get('base_url', '')
        self.vlm_api_key = vlm_api_key or _vlm_cfg.get('api_key', '')
        self.vlm_model = vlm_model or _vlm_cfg.get('model', 'Qwen/Qwen2.5-VL-72B-Instruct')
        
        # 速率限制配置
        self.rate_config = rate_limit_config or RateLimitConfig(
            requests_per_minute=_rate_limit_cfg.get('requests_per_minute', self.config.get('requests_per_minute', 60)),
            requests_per_second=_rate_limit_cfg.get('requests_per_second', self.config.get('requests_per_second', 2)),
            max_retries=_rate_limit_cfg.get('max_retries', self.config.get('max_retries', 5)),
            base_delay=_rate_limit_cfg.get('base_delay', 1.0),
            max_delay=_rate_limit_cfg.get('max_delay', 60.0),
            retry_on_429=_rate_limit_cfg.get('retry_on_429', True),
            respect_retry_after=_rate_limit_cfg.get('respect_retry_after', True),
        )

        bucket_rate = max(float(self.rate_config.requests_per_second), 0.1)
        bucket_capacity = max(bucket_rate, 1.0)

        self.llm_bucket = TokenBucket(
            rate=bucket_rate,
            capacity=bucket_capacity
        )
        self.vlm_bucket = TokenBucket(
            rate=bucket_rate,
            capacity=bucket_capacity
        )
        
        # 统计信息
        self._stats = {
            'llm_requests': 0,
            'vlm_requests': 0,
            'llm_retries': 0,
            'vlm_retries': 0,
            'rate_limited': 0
        }
        
        # HTTP会话
        self._session: Optional[aiohttp.ClientSession] = None
        
        logger.info(f"API客户端初始化: LLM={self.llm_model}, VLM={self.vlm_model}")

    def _load_managed_config(self):
        """优先使用 ConfigManager 作为单一配置源。"""
        if not CONFIG_MANAGER_AVAILABLE:
            return None
        try:
            return ConfigManager.get_instance()
        except Exception as e:
            logger.warning(f"ConfigManager 加载失败，回退到 YAML 读取: {e}")
            return None
    
    def _load_config(self):
        """加载配置文件"""
        try:
            import yaml
            from pathlib import Path
            
            config_path = Path("config.yaml")
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.config = yaml.safe_load(f) or {}
            else:
                self.config = {}
        except Exception as e:
            logger.warning(f"配置文件加载失败: {e}")
            self.config = {}
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=300),
            headers={'Content-Type': 'application/json'}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self._session:
            await self._session.close()
    
    async def _make_request(
        self,
        url: str,
        api_key: str,
        data: Dict,
        model: str,
        bucket: TokenBucket,
        max_tokens: int = 4096,
        timeout: int = 120
    ) -> Dict:
        """
        发起API请求（带速率限制和重试）
        
        Args:
            url: API地址
            api_key: API密钥
            data: 请求数据
            model: 模型名称
            bucket: 令牌桶
            max_tokens: 最大token数
            timeout: 超时时间(秒)
            
        Returns:
            API响应
        """
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        # 构建请求
        request_data = {
            'model': model,
            **data
        }
        
        last_error = None
        retry_count = 0
        
        for attempt in range(self.rate_config.max_retries):
            try:
                # 等待令牌
                await bucket.async_consume(1.0)
                
                async with self._session.post(
                    url,
                    headers=headers,
                    json=request_data,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    status = response.status
                    
                    if status == 200:
                        result = await response.json()

                        if 'error' in result:
                            error_msg = result['error'].get('message', str(result['error']))
                            raise Exception(f"API业务错误: {error_msg}")

                        return result
                    
                    elif status == 429:
                        # 速率限制
                        self._stats['rate_limited'] += 1
                        
                        if not self.rate_config.retry_on_429:
                            raise Exception(f"API速率限制 (429): {response.reason}")
                        
                        # 获取Retry-After头
                        retry_after = None
                        if self.rate_config.respect_retry_after:
                            retry_after = response.headers.get('Retry-After')
                        
                        if retry_after:
                            try:
                                wait_time = float(retry_after)
                            except (ValueError, TypeError):
                                wait_time = self.rate_config.base_delay * (2 ** attempt)
                        else:
                            wait_time = min(
                                self.rate_config.base_delay * (2 ** attempt),
                                self.rate_config.max_delay
                            )
                        jitter = random.uniform(0, wait_time * 0.25)
                        wait_time += jitter
                        
                        logger.warning(
                            f"API速率限制触发，等待 {wait_time:.1f}秒 "
                            f"(尝试 {attempt + 1}/{self.rate_config.max_retries})"
                        )
                        
                        await asyncio.sleep(wait_time)
                        retry_count += 1
                        continue
                    
                    elif status == 401:
                        raise Exception("API认证失败，请检查API密钥")
                    
                    elif status == 500:
                        wait_time = self.rate_config.base_delay * (2 ** attempt)
                        jitter = random.uniform(0, wait_time * 0.25)
                        wait_time += jitter
                        logger.warning(f"API服务器错误 (500)，等待 {wait_time:.1f}秒后重试")
                        await asyncio.sleep(wait_time)
                        retry_count += 1
                        continue
                    
                    else:
                        error_text = await response.text()
                        raise Exception(f"API错误 ({status}): {error_text[:200]}")
                        
            except asyncio.TimeoutError:
                last_error = f"请求超时 (>{timeout}秒)"
                wait_time = self.rate_config.base_delay * (2 ** attempt)
                jitter = random.uniform(0, wait_time * 0.25)
                wait_time += jitter
                logger.warning(f"{last_error}，等待 {wait_time:.1f}秒后重试")
                await asyncio.sleep(wait_time)
                retry_count += 1
                continue
                
            except aiohttp.ClientError as e:
                last_error = str(e)
                wait_time = self.rate_config.base_delay * (2 ** attempt)
                jitter = random.uniform(0, wait_time * 0.25)
                wait_time += jitter
                logger.warning(f"请求失败: {e}，等待 {wait_time:.1f}秒后重试")
                await asyncio.sleep(wait_time)
                retry_count += 1
                continue
        
        # 所有重试都失败
        raise Exception(
            f"API请求失败，已重试 {retry_count} 次: {last_error}"
        )
    
    def _extract_openai_chat_text(self, result: Dict[str, Any], model_type: str) -> str:
        if "choices" not in result or not result["choices"]:
            raise Exception(f"{model_type} API 响应结构异常：choices 缺失或为空")
        choice = result["choices"][0]
        message = choice.get("message") or choice.get("delta") or {}

        # 优先取 content，若为空则尝试 reasoning_content（部分模型将输出放在此处）
        content = message.get("content")
        if not content:
            content = message.get("reasoning_content")
        if content:
            return content

        raise Exception(f"{model_type} API 返回空正文内容（content 和 reasoning_content 均为空）")

    def _extract_provider_text_fallback(self, result: Dict[str, Any], model_type: str) -> str:
        for key in ("output_text", "text", "response", "content", "output", "result"):
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        long_strs = [v for v in result.values() if isinstance(v, str) and len(v) > 50]
        if long_strs:
            logger.warning(f"{model_type} provider 使用 fallback 字段，响应 keys: {list(result.keys())}")
            return long_strs[0]
        logger.warning(f"{model_type} 响应 keys: {list(result.keys())}, values: { {k: str(v)[:100] for k, v in result.items()} }")
        raise Exception(f"{model_type} API 响应中未找到可用文本字段 | keys: {list(result.keys())}")

    def _extract_message_text(
        self,
        result: Dict[str, Any],
        *,
        allow_reasoning_fallback: bool = False,
        model_type: str = "llm"
    ) -> str:
        try:
            return self._extract_openai_chat_text(result, model_type)
        except Exception as e:
            logger.warning(f"{model_type} OpenAI 格式解析失败: {e}，尝试 fallback")
            # 特殊处理：如果 choices 为 null，抛出明确错误
            if result.get("choices") is None or not isinstance(result.get("choices"), list):
                raise Exception(f"{model_type} API 返回无效响应: choices 为 null 或缺失")
            return self._extract_provider_text_fallback(result, model_type)

    async def chat_completion_text(
        self,
        messages: List[Dict],
        temperature: float = 0.1,
        max_tokens: int = 8192,
        extra_params: Optional[Dict] = None
    ) -> str:
        url = f"{self.llm_base_url.rstrip('/')}/chat/completions"

        data = {
            'model': self.llm_model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens
        }

        if 'thinking' not in (extra_params or {}):
            data['thinking'] = {"type": "disabled"}
        else:
            data['thinking'] = extra_params.pop('thinking')

        if extra_params:
            data.update(extra_params)

        result = await self._make_request(
            url=url,
            api_key=self.llm_api_key,
            data=data,
            model=self.llm_model,
            bucket=self.llm_bucket,
            max_tokens=max_tokens
        )

        self._stats['llm_requests'] += 1

        return self._extract_message_text(result, allow_reasoning_fallback=False, model_type="LLM")
    
    async def chat_completion_vision(
        self,
        messages: List[Dict],
        temperature: float = 0.1,
        max_tokens: int = 2048
    ) -> str:
        """
        VLM图像分析
        
        Args:
            messages: 包含图像的消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            
        Returns:
            生成的文本
        """
        url = f"{self.vlm_base_url.rstrip('/')}/chat/completions"
        
        data = {
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'thinking': {"type": "disabled"}
        }
        
        result = await self._make_request(
            url=url,
            api_key=self.vlm_api_key,
            data=data,
            model=self.vlm_model,
            bucket=self.vlm_bucket,
            max_tokens=max_tokens,
            timeout=180  # VLM超时更长
        )

        # 检测空 choices 情况（Kimi-K2.5 等模型可能出现）
        if not result.get("choices"):
            raise Exception(
                f"VLM API 返回空 choices，可能为服务端错误或不支持的请求格式 | "
                f"model={self.vlm_model} | base_url={self.vlm_base_url} | "
                f"result_keys={list(result.keys()) if isinstance(result, dict) else type(result).__name__}"
            )
        
        self._stats['vlm_requests'] += 1

        try:
            return self._extract_message_text(result, allow_reasoning_fallback=False, model_type="VLM")
        except Exception as e:
            logger.error(
                f"VLM 解析失败 | model={self.vlm_model} | base_url={self.vlm_base_url} | "
                f"result_keys={list(result.keys()) if isinstance(result, dict) else type(result).__name__} | "
                f"raw_preview={str(result)[:500]}"
            )
            raise
    
    async def test_connection(self, model_type: str = 'text') -> Dict:
        import time
        import base64
        try:
            if model_type == 'text':
                start_time = time.time()
                # 使用 chat_completion_text 方法（自动禁用思考模式），避免 reasoning_content 问题
                try:
                    response = await self.chat_completion_text(
                        messages=[{"role": "user", "content": "Reply 'ok' only with the word 'ok'."}],
                        temperature=0.0,
                        max_tokens=10,
                    )
                    return {
                        "success": True,
                        "message": f"连接成功 (响应: {response[:50]})",
                        "response_time": time.time() - start_time
                    }
                except Exception as e:
                    logger.warning(f"[test_connection:text] 测试失败: {e}")
                    return {
                        "success": False,
                        "message": f"连接失败: {str(e)}",
                        "response_time": time.time() - start_time
                    }

            # vision 分支：先尝试纯文本测试（避免图像格式兼容性问题）
            start_time = time.time()
            try:
                # 先用纯文本测试 VLM 连通性
                response = await self.chat_completion_vision(
                    messages=[{"role": "user", "content": "Reply 'ok' only with the word 'ok'."}],
                    temperature=0.0,
                    max_tokens=10
                )
                return {
                    "success": True,
                    "message": f"连接成功 (纯文本响应: {response[:50]})",
                    "response_time": time.time() - start_time
                }
            except Exception as text_err:
                logger.warning(f"[test_connection:vision] 纯文本测试失败: {text_err}，尝试图像测试...")
                # 纯文本失败后回退到带图像的原始测试逻辑
                url = f"{self.vlm_base_url.rstrip('/')}/chat/completions"
                api_key = self.vlm_api_key
                model = self.vlm_model

            is_local = "127.0.0.1" in self.vlm_base_url or "localhost" in self.vlm_base_url

            if is_local:
                text_prompt = "Reply 'ok' if you can read this."
                data = {
                    'model': model,
                    'messages': [{"role": "user", "content": text_prompt}],
                    'max_tokens': 10,
                    'temperature': 0.1
                }
            else:
                tiny_png_b64 = (
                    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
                )
                image_data_url = f"data:image/png;base64,{tiny_png_b64}"
                vision_prompt = (
                    "You are a tiny image test. Reply with ONLY this exact JSON, nothing else:\n"
                    '{"status": "ok", "model": "vision_test_passed"}'
                )
                data = {
                    'model': model,
                    'messages': [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": vision_prompt},
                                {"type": "image_url", "image_url": {"url": image_data_url}},
                            ],
                        }
                    ],
                    'max_tokens': 100,
                    'temperature': 0.1
                }

            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }

            start_time = time.time()
            async with self._session.post(
                url,
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                response_time = time.time() - start_time
                status = response.status
                raw_body = await response.read()

            if status != 200:
                return {
                    "success": False,
                    "message": f"API错误 ({status}): {raw_body.decode('utf-8', errors='replace')[:300]}",
                    "response_time": response_time
                }

            try:
                result = json.loads(raw_body.decode("utf-8", errors="replace"))
                logger.info(f"[test_connection:{model_type}] 原始响应: {result}")
            except Exception as e:
                return {
                    "success": False,
                    "message": f"响应解析失败: {str(e)} | raw: {raw_body[:500]}",
                    "response_time": response_time
                }

            try:
                content = self._extract_message_text(
                    result,
                    allow_reasoning_fallback=False,
                    model_type="connection"
                )
                return {
                    "success": True,
                    "message": f"连接成功 (响应时间: {response_time:.2f}s)",
                    "response_time": response_time
                }
            except Exception as e:
                logger.warning(f"[test_connection:{model_type}] 提取内容失败: {str(e)} | result: {result}")
                return {
                    "success": False,
                    "message": f"连接测试失败: {str(e)}",
                    "response_time": response_time
                }

        except asyncio.TimeoutError:
            return {
                'success': False,
                'message': '连接超时 (>120秒)',
                'response_time': 120.0
            }
        except Exception as e:
            import traceback
            logger.error(f"[test_connection:{model_type}] 异常: {traceback.format_exc()}")
            return {
                'success': False,
                'message': f'连接失败: {str(e)}',
                'response_time': 0.0
            }
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        total_requests = self._stats['llm_requests'] + self._stats['vlm_requests']
        total_retries = self._stats['llm_retries'] + self._stats['vlm_retries']
        
        return {
            **self._stats,
            'total_requests': total_requests,
            'total_retries': total_retries,
            'retry_rate': round(total_retries / total_requests, 3) if total_requests else 0
        }
    
    def reset_statistics(self):
        """重置统计信息"""
        self._stats = {
            'llm_requests': 0,
            'vlm_requests': 0,
            'llm_retries': 0,
            'vlm_retries': 0,
            'rate_limited': 0
        }


# ========== 便捷函数 ==========

_async_client: Optional[APIClient] = None


async def get_async_client() -> APIClient:
    """获取异步客户端单例"""
    global _async_client
    if _async_client is None:
        _async_client = APIClient()
        await _async_client.__aenter__()
    return _async_client


async def close_async_client():
    """关闭异步客户端"""
    global _async_client
    if _async_client:
        await _async_client.__aexit__(None, None, None)
        _async_client = None
