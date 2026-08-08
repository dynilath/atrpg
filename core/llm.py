"""llm.py --- OpenAI 兼容 LLM 客户端封装（多模型 / 工作场景）。

模型管理采用「模型库 + 工作场景」分离模式（见 core/config.py）：
- 模型库：多个 ModelProfile，每项含 base_url/api_key/model/thinking 等参数。
- 工作场景：chat / utility / utility_large / embedding 等，通过名称引用模型库中的配置。

提供两种调用：
- chat(system, user, workflow="chat")：一次性文本对话，无工具。
- chat_with_tools(messages, tools, workflow="chat")：单步工具调用循环。

思考参数：
- profile.thinking=True → extra_body={"thinking": {"type": "enabled"}}
- profile.reasoning_effort 非空 → extra_body={"reasoning_effort": <值>}

客户端按 (base_url, api_key) 缓存，支持不同模型使用不同厂商端点。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from .config import ModelProfile, load_config, resolve_profile

logger = logging.getLogger(__name__)
_clients: dict[tuple[str, str], AsyncOpenAI] = {}


def _client_for(profile: ModelProfile) -> AsyncOpenAI:
    """按 (base_url, api_key) 取客户端（多厂商共存）。"""
    key = (profile.base_url, profile.api_key)
    if key not in _clients:
        _clients[key] = AsyncOpenAI(base_url=profile.base_url, api_key=profile.api_key, timeout=60.0)
    return _clients[key]


def client(workflow: str = "chat") -> AsyncOpenAI:
    """取 chat 工作流（或指定工作流）对应模型的客户端。

    兼容旧调用（无参）：返回 chat 工作流的客户端。
    """
    return _client_for(resolve_profile(workflow))


def completion_kwargs(p: ModelProfile) -> dict[str, Any]:
    """构造模型请求的公共 kwargs（temperature/max_tokens/思考参数）。

    供自定义工具循环（如 editor_chat）复用，避免重复实现思考参数逻辑。
    """
    kwargs: dict[str, Any] = {
        "temperature": p.temperature if p.temperature is not None else 0.8,
    }
    if p.max_tokens:
        kwargs["max_tokens"] = p.max_tokens

    extra: dict[str, Any] = {}
    if p.thinking:
        extra["thinking"] = {"type": "enabled"}
    if p.reasoning_effort:
        extra["reasoning_effort"] = p.reasoning_effort
    if extra:
        kwargs["extra_body"] = extra
    return kwargs


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


async def chat(system: str, user: str, *, workflow: str = "chat") -> str:
    """一次对话调用，返回纯文本回复（无工具）。

    workflow: 工作场景名（chat/utility/utility_large/embedding 等），
    决定使用模型库中的哪个配置。
    """
    p = resolve_profile(workflow)
    kwargs = completion_kwargs(p)
    resp = await _client_for(p).chat.completions.create(
        model=p.model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **kwargs,
    )
    return resp.choices[0].message.content or ""


async def chat_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    workflow: str = "chat",
) -> AssistantMessage:
    """单步工具调用：把当前 messages 发给模型，返回助手这一步的输出。

    - tools：OpenAI 兼容的函数工具 schema 列表。
    - workflow：工作场景名（默认 chat）。
    - 返回 AssistantMessage；若 tool_calls 非空，调用方应执行工具、把
      tool 结果以 {"role":"tool", "tool_call_id":..., "content":...} 追加到
      messages，然后再次调用本函数继续循环。
    - 不设 tool_choice，默认 auto，交由模型自行决定是否调用工具。
    """
    import json

    p = resolve_profile(workflow)
    kwargs = completion_kwargs(p)
    logger.info(f"LLM call: workflow={workflow} model={p.model} msgs={len(messages)} tools={len(tools)}")
    resp = await _client_for(p).chat.completions.create(
        model=p.model,
        messages=messages,
        tools=tools,
        **kwargs,
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


def tool_result_message(tool_call_id: str, content: str, turn_no: int | None = None) -> dict[str, Any]:
    """构造工具结果消息（追加到 messages 续接循环）。

    turn_no 可选：传入时在 content 末尾追加 HTML 注释 <!-- turn:N -->，
    供 Tool Output Folding 机制识别消息轮次。注释对 LLM 不可见但消耗少量 token。
    """
    if turn_no is not None:
        content = f"{content}\n<!-- turn:{turn_no} -->"
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}
