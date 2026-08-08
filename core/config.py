"""config.py --- 统一配置加载。

从项目根目录 config.toml 读取 [server] / [atrpg] 段配置，
从同目录 models.toml（若存在）读取模型库与工作场景映射。
被 core/、server/、bot/ 共同使用。

模型管理采用「模型库 + 工作场景」分离模式：
- 模型库（models.toml 的 [[models]]）：多个模型配置，每项有用户自定义名称，
  以及 base_url/api_key/model/thinking（思考参数）等。
- 工作场景（models.toml 的 [workflows]）：如 chat/utility/utility_large/embedding，
  每个场景通过名称引用一个模型配置。
- 兼容：无 models.toml 时，回退使用 config.toml [atrpg] 的
  llm_base_url/llm_api_key/llm_model/llm_utility_model 旧字段构造默认模型。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ModelProfile:
    """一个模型配置（模型库中的一项）。

    thinking: 是否启用思考（reasoning）。true 时请求会带
        extra_body={"thinking": {"type": "enabled"}}（DeepSeek/Kimi 等兼容）。
    reasoning_effort: 可选，如 "low"/"medium"/"high"（OpenAI 系）。
    temperature/max_tokens: 可选，覆盖默认值。
    """

    name: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    thinking: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None


@dataclass
class AppConfig:
    game_dir: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-pro"
    llm_utility_model: str = "deepseek-v4-flash"
    dev_mode: bool = True
    admin_users: list[str] = field(default_factory=list)
    # --- 模型库 / 工作场景（新） ---
    models: list[ModelProfile] = field(default_factory=list)
    workflows: dict[str, str] = field(default_factory=dict)
    editor_workflows: dict[str, str] = field(default_factory=dict)
    models_toml_path: str = ""


def _find_config() -> Path:
    """从项目根目录或工作目录查找 config.toml。"""
    import os

    # 优先：项目根（基于本文件位置推算）
    proj_root = Path(__file__).resolve().parent.parent
    p = proj_root / "config.toml"
    if p.exists():
        return p

    # 回退：工作目录及父目录
    start = Path(os.getcwd())
    for d in [start, start.parent, start / "bot"]:
        p = d / "config.toml"
        if p.exists():
            return p
    raise FileNotFoundError(
        "找不到 config.toml。请放在项目根目录或指定 ATRPG_CONFIG 环境变量。"
    )


def _parse_profile(raw: dict[str, Any]) -> ModelProfile:
    """从 TOML dict 解析 ModelProfile（容忍缺字段/类型不规范）。"""
    def _as_str(v: Any, default: str = "") -> str:
        return "" if v is None else str(v)

    def _as_bool(v: Any, default: bool = False) -> bool:
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    def _as_float(v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _as_int(v: Any) -> int | None:
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return ModelProfile(
        name=_as_str(raw.get("name")),
        base_url=_as_str(raw.get("base_url")),
        api_key=_as_str(raw.get("api_key")),
        model=_as_str(raw.get("model")),
        thinking=_as_bool(raw.get("thinking"), False),
        temperature=_as_float(raw.get("temperature")),
        max_tokens=_as_int(raw.get("max_tokens")),
        reasoning_effort=_as_str(raw.get("reasoning_effort")) or None,
    )


def _load_models_toml(config_path: Path, ac: AppConfig) -> None:
    """加载 models.toml（模型库 + 工作场景）；不存在时用旧字段构造默认模型。"""
    mt_path = config_path.parent / "models.toml"
    ac.models_toml_path = str(mt_path)

    if mt_path.exists():
        try:
            mraw = tomllib.loads(mt_path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            mraw = {}
        models = [_parse_profile(m) for m in mraw.get("models", []) if isinstance(m, dict)]
        if models:
            ac.models = models
            ac.workflows = {str(k): str(v) for k, v in (mraw.get("workflows") or {}).items()}
            ac.editor_workflows = {str(k): str(v) for k, v in (mraw.get("editor_workflows") or {}).items()}
        # models 为空：视为无效，落回旧字段（不覆盖 ac.models 默认空）

    if not ac.models:
        # 旧字段回退：构造 default 模型 + 可选 utility 模型
        fallback = [
            ModelProfile(
                name="default",
                base_url=ac.llm_base_url,
                api_key=ac.llm_api_key,
                model=ac.llm_model,
            )
        ]
        if ac.llm_utility_model and ac.llm_utility_model != ac.llm_model:
            fallback.append(
                ModelProfile(
                    name="utility",
                    base_url=ac.llm_base_url,
                    api_key=ac.llm_api_key,
                    model=ac.llm_utility_model,
                )
            )
        ac.models = fallback
        ac.workflows = {"chat": "default", "utility": "utility" if len(fallback) > 1 else "default"}
        ac.editor_workflows = {}

    # 工作场景兜底：chat/utility 必须有效；其余场景空值保留（运行时自动回退第一个模型），
    # 仅修正「非空但引用不存在」的失效配置
    if not ac.workflows.get("chat") or not _find_profile(ac, ac.workflows.get("chat")):
        ac.workflows["chat"] = ac.models[0].name
    if not ac.workflows.get("utility") or not _find_profile(ac, ac.workflows.get("utility")):
        ac.workflows["utility"] = ac.models[0].name
    for k, v in list(ac.workflows.items()):
        if v and not _find_profile(ac, v):
            ac.workflows[k] = ac.models[0].name


def _find_profile(ac: AppConfig, name: str | None) -> ModelProfile | None:
    if not name:
        return None
    for m in ac.models:
        if m.name == name:
            return m
    return None


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """加载配置。

    优先使用传入路径，否则自动查找。
    支持 env override：ATRPG_CONFIG 指定 config 路径，
    ATRPG_GAME_DIR 覆盖 game_dir。
    """
    import os

    if config_path is None:
        config_path = os.environ.get("ATRPG_CONFIG", "")
        if not config_path:
            config_path = _find_config()
        else:
            config_path = Path(config_path)

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置不存在: {config_path}")

    raw = config_path.read_text(encoding="utf-8")
    cfg = tomllib.loads(raw)

    ac = AppConfig()

    # [atrpg] 段（旧字段，作为回退与兼容）
    atrpg = cfg.get("atrpg", {})
    ac.game_dir = os.environ.get("ATRPG_GAME_DIR", atrpg.get("game_dir", ""))
    ac.llm_base_url = atrpg.get("llm_base_url", ac.llm_base_url)
    ac.llm_api_key = atrpg.get("llm_api_key", ac.llm_api_key)
    ac.llm_model = atrpg.get("llm_model", ac.llm_model)
    ac.llm_utility_model = atrpg.get("llm_utility_model", ac.llm_utility_model)
    ac.admin_users = atrpg.get("admin_users", ac.admin_users)

    # [server] 段
    server = cfg.get("server", {})
    ac.dev_mode = server.get("dev_mode", ac.dev_mode)

    # 模型库 / 工作场景（models.toml 优先）
    _load_models_toml(config_path, ac)

    return ac


def resolve_profile(workflow: str = "chat") -> ModelProfile:
    """按工作场景名解析模型配置；场景缺失或引用无效时回退到第一个模型。

    同时检查 workflows 和 editor_workflows。
    """
    ac = load_config()
    name = ac.workflows.get(workflow, "") or ac.editor_workflows.get(workflow, "")
    p = _find_profile(ac, name)
    if p:
        return p
    if ac.models:
        return ac.models[0]
    raise RuntimeError("未配置任何模型（models.toml 缺失且 [atrpg] 无 LLM 字段）")


def workflows_of() -> dict[str, str]:
    """返回工作场景→模型名映射（不含回退修正，供配置页展示）。"""
    ac = load_config()
    return dict(ac.workflows)


def resolve_editor_profile(kind: str) -> ModelProfile:
    """按编辑任务类型解析模型配置。

    查找链：editor_workflows[kind] → workflows["chat"] → models[0]
    editor_workflow 值为空字符串时，回退到 chat workflow。
    找不到对应模型时，回退到第一个模型。

    Args:
        kind: 内容类型 key（story_arc, character, npc, item, scene, location, terminology, state_record）

    Returns:
        ModelProfile 实例
    """
    ac = load_config()
    name = ac.editor_workflows.get(kind, "")
    if name:
        p = _find_profile(ac, name)
        if p:
            return p
    # 回退到 chat workflow
    return resolve_profile("chat")


def editor_workflows_of() -> dict[str, str]:
    """返回编辑任务→模型名映射（供配置页展示）。"""
    ac = load_config()
    return dict(ac.editor_workflows)
