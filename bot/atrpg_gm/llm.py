"""llm.py — OpenAI 兼容 LLM 客户端封装。

提供两种调用：
- chat(system, user)：一次性文本对话，无工具。
- chat_with_tools(messages, tools)：单步工具调用循环。返回助手消息（可能含
  tool_calls），由调用方决定是否继续循环。gm.py 用它编排「主持人演绎 + 落盘」。

配置加载：
- 优先通过 NoneBot 的 get_driver().config 读取（QQ Bot 模式）。
- 回退从 config.toml 直接读取（独立 web_api 模式）。
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
_client: AsyncOpenAI | None = None


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    utility_model: str


def config() -> LLMConfig:
    # 优先从 NoneBot 配置读取（QQ Bot 模式）
    try:
        from nonebot import get_driver
        cfg = get_driver().config
        return LLMConfig(
            base_url=cfg.atrpg_llm_base_url,
            api_key=cfg.atrpg_llm_api_key,
            model=getattr(cfg, "atrpg_llm_model", "glm-4-plus"),
            utility_model=getattr(cfg, "atrpg_llm_utility_model", "glm-4-flash"),
        )
    except (ValueError, AttributeError, ImportError):
        pass

    # 回退：从 config.toml 直接读取（独立 web_api 模式）
    return _config_from_toml()


def _config_from_toml() -> LLMConfig:
    """从 config.toml 读取 LLM 配置（NoneBot 不可用时回退）。"""
    for d in [Path.cwd(), Path.cwd().parent, Path.cwd() / "bot"]:
        p = d / "config.toml"
        if p.exists():
            raw = p.read_text(encoding="utf-8")
            cfg = tomllib.loads(raw)
            atrpg = cfg.get("atrpg", {})
            return LLMConfig(
                base_url=atrpg.get("llm_base_url", ""),
                api_key=atrpg.get("llm_api_key", ""),
                model=atrpg.get("llm_model", "glm-4-plus"),
                utility_model=atrpg.get("llm_utility_model", "glm-4-flash"),
            )
    raise RuntimeError("找不到 config.toml，无法获取 LLM 配置")


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        c = config()
        _client = AsyncOpenAI(base_url=c.base_url, api_key=c.api_key, timeout=60.0)
    return _client


@dataclass
class ToolCall:
    """一次工具调用的结构化表示。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantMessage:
    """一轮 LLM 回复：纯文本内容 + 可能的工具调用 + token 用量。

    content 为助手输出的可见文本（可为空）。
    tool_calls 为它要求执行的工具；为空表示这轮不需要调用工具（通常是收尾）。
    usage 为本轮 token 用量（prompt_tokens/completion_tokens/cached_tokens），
    用于成本监控与缓存命中观察。
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


async def chat(system: str, user: str, model: str | None = None) -> str:
    """一次对话调用，返回纯文本回复（无工具）。"""
    c = config()
    m = model or c.model
    resp = await client().chat.completions.create(
        model=m,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.8,
    )
    return resp.choices[0].message.content or ""


async def chat_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
) -> AssistantMessage:
    """单步工具调用：把当前 messages 发给模型，返回助手这一步的输出。

    - tools：OpenAI 兼容的函数工具 schema 列表。
    - 返回 AssistantMessage；若 tool_calls 非空，调用方应执行工具、把
      tool 结果以 {"role":"tool", "tool_call_id":..., "content":...} 追加到
      messages，然后再次调用本函数继续循环。
    - 不设 tool_choice，默认 auto，交由模型自行决定是否调用工具。
    """
    import json

    c = config()
    m = model or c.model
    logger.info(f"LLM call: model={m} msgs={len(messages)} tools={len(tools)}")
    resp = await client().chat.completions.create(
        model=m,
        messages=messages,
        tools=tools,
        temperature=0.8,
    )
    msg = resp.choices[0].message
    content = msg.content or ""
    logger.debug(
        f"LLM resp: content={len(content)}chars tool_calls={len(msg.tool_calls or [])}"
    )

    tool_calls: list[ToolCall] = []
    for tc in msg.tool_calls or []:
        try:
            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
        except (json.JSONDecodeError, AttributeError):
            args = {}
        tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

    # 提取 token 用量（含前缀缓存命中数，DeepSeek/OpenAI 兼容协议）
    usage: dict[str, int] = {}
    if resp.usage:
        cached = 0
        if resp.usage.prompt_tokens_details:
            cached = getattr(resp.usage.prompt_tokens_details, "cached_tokens", 0) or 0
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens or 0,
            "completion_tokens": resp.usage.completion_tokens or 0,
            "cached_tokens": cached,
        }

    return AssistantMessage(content=content, tool_calls=tool_calls, usage=usage)


def assistant_to_message(msg: AssistantMessage) -> dict[str, Any]:
    """把 AssistantMessage 转回 OpenAI messages 格式，用于续接对话。

    带工具调用时，content 可为空字符串，但 tool_calls 字段必须按协议存在。
    """
    if msg.has_tool_calls:
        return {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        # arguments 必须是 JSON 字符串（协议要求）
                        "arguments": __import__("json").dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in msg.tool_calls
            ],
        }
    return {"role": "assistant", "content": msg.content}


def tool_result_message(tool_call_id: str, content: str) -> dict[str, Any]:
    """构造工具结果消息（追加到 messages 续接循环）。"""
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}
