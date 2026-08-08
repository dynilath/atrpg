"""config_routes.py --- /api/config/* AI 接口与 QQ Bot 配置。"""

from __future__ import annotations

import json
import logging
import tomllib
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from server.deps import get_config as _get_web_config
from core import db as _db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/config", tags=["config"])

# --- QQ Bot QR 流程状态（进程内存） ---
_qr_state: dict[str, Any] = {"task_id": None, "aes_key": None, "status": "", "app_id": "", "secret": ""}


def _find_config_toml() -> Path:
    """找到项目使用的 config.toml。"""
    import os
    env = os.environ.get("ATRPG_CONFIG", "")
    if env:
        return Path(env)

    # 优先：项目根（基于本文件位置推算）
    proj_root = Path(__file__).resolve().parent.parent.parent
    p = proj_root / "config.toml"
    if p.exists():
        return p

    from pathlib import Path as _P
    start = _P.cwd()
    for d in [start, start.parent, start / "bot"]:
        p = d / "config.toml"
        if p.exists():
            return p
    raise FileNotFoundError("找不到 config.toml")


# ═══════════════════════════════════════════════════════════════════
# 模型库 / 工作场景（读写项目根 models.toml）
# ═══════════════════════════════════════════════════════════════════
# 模型管理采用「模型库 + 工作场景」分离：
#   [[models]]    多个模型配置（name/base_url/api_key/model/thinking 等）
#   [workflows]   chat/utility/utility_large/embedding → 模型配置名

def _models_path() -> Path:
    """models.toml 与 config.toml 同目录。"""
    return _find_config_toml().parent / "models.toml"


def _read_models_data() -> dict[str, Any]:
    """读取 models.toml；不存在或损坏返回空 dict。"""
    p = _models_path()
    if p.exists():
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (tomllib.TOMLDecodeError, OSError):
            logger.warning("models.toml 解析失败，按空处理")
    return {}


def _write_models_data(data: dict[str, Any]) -> None:
    """用 tomli_w 全量写回 models.toml（保留注释需人工维护，配置页写入结构简单）。"""
    import tomli_w
    _models_path().write_text(tomli_w.dumps(data), encoding="utf-8")


@router.get("/models")
async def get_models():
    """读取模型库（models.toml [[models]]）。无 models.toml 时回退 config.toml 旧字段。"""
    try:
        data = _read_models_data()
        models = data.get("models")
        if not models:
            # 兼容：无 models.toml 时从 config.toml 旧字段构造单模型
            p = _find_config_toml()
            atrpg = tomllib.loads(p.read_text(encoding="utf-8")).get("atrpg", {})
            models = [{
                "name": "default",
                "base_url": atrpg.get("llm_base_url", ""),
                "api_key": atrpg.get("llm_api_key", ""),
                "model": atrpg.get("llm_model", ""),
                "thinking": False,
            }]
        return JSONResponse({"models": models})
    except Exception as e:
        return JSONResponse({"models": [], "error": str(e)}, status_code=500)


@router.post("/models")
async def save_models(body: dict[str, Any]):
    """全量保存模型库到 models.toml。

    body: {"models": [{name, base_url, api_key, model, thinking, temperature?, max_tokens?, reasoning_effort?}]}
    name 必填且唯一；允许空 base_url（模型库可以先建名称再补参数）。
    """
    models = body.get("models")
    if not isinstance(models, list):
        return JSONResponse({"error": "models 必须是数组"}, status_code=400)

    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in models:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name", "")).strip()
        if not name:
            return JSONResponse({"error": "每个模型必须有 name"}, status_code=400)
        if name in seen:
            return JSONResponse({"error": f"模型名称重复: {name}"}, status_code=400)
        seen.add(name)
        entry: dict[str, Any] = {
            "name": name,
            "base_url": str(m.get("base_url", "") or ""),
            "api_key": str(m.get("api_key", "") or ""),
            "model": str(m.get("model", "") or ""),
            "thinking": bool(m.get("thinking", False)),
        }
        for k in ("temperature", "max_tokens", "reasoning_effort"):
            if m.get(k) not in (None, ""):
                entry[k] = m[k]
        cleaned.append(entry)

    if not cleaned:
        return JSONResponse({"error": "模型库不能为空"}, status_code=400)

    data = _read_models_data()
    data["models"] = cleaned

    # 工作场景引用失效修正：引用不存在的模型时改指第一个模型
    workflows = data.get("workflows") or {}
    for k, v in list(workflows.items()):
        if v not in seen:
            workflows[k] = cleaned[0]["name"]
    data["workflows"] = workflows

    try:
        _write_models_data(data)
    except Exception as e:
        logger.exception("保存模型库失败")
        return JSONResponse({"error": f"写入失败: {e}"}, status_code=500)
    logger.info(f"保存模型库: {[m['name'] for m in cleaned]}")
    return JSONResponse({"ok": True, "models": cleaned})


@router.get("/workflows")
async def get_workflows():
    """读取工作场景映射（models.toml [workflows]）。"""
    try:
        data = _read_models_data()
        wf = data.get("workflows")
        if not wf:
            # 兼容：回退 config.toml 旧字段语义
            p = _find_config_toml()
            atrpg = tomllib.loads(p.read_text(encoding="utf-8")).get("atrpg", {})
            wf = {"chat": "default", "utility": "default"}
            if atrpg.get("llm_model"):
                wf = {"chat": "default", "utility": "default"}
        return JSONResponse({"workflows": wf})
    except Exception as e:
        return JSONResponse({"workflows": {}, "error": str(e)}, status_code=500)


@router.post("/workflows")
async def save_workflows(body: dict[str, Any]):
    """全量保存工作场景映射到 models.toml。

    body: {"workflows": {"chat": "模型名", "utility": "模型名", ...}}
    只允许引用模型库中已存在的名称。
    """
    wf = body.get("workflows")
    if not isinstance(wf, dict):
        return JSONResponse({"error": "workflows 必须是对象"}, status_code=400)

    data = _read_models_data()
    names = [str(m.get("name", "")) for m in data.get("models", []) if isinstance(m, dict)]
    if not names:
        return JSONResponse({"error": "模型库为空，请先保存模型"}, status_code=400)

    cleaned: dict[str, str] = {}
    for k, v in wf.items():
        k = str(k).strip()
        if not k:
            continue
        v = str(v or "").strip()
        # 引用失效（模型被删除等）时自动改指第一个模型，避免配置卡死
        if v and v not in names:
            v = names[0]
        cleaned[k] = v

    data["workflows"] = cleaned
    try:
        _write_models_data(data)
    except Exception as e:
        logger.exception("保存工作场景失败")
        return JSONResponse({"error": f"写入失败: {e}"}, status_code=500)
    logger.info(f"保存工作场景: {cleaned}")
    return JSONResponse({"ok": True, "workflows": cleaned})


# ═══════════════════════════════════════════════════════════════════
# AI 配置（旧端点，兼容保留：读写 chat 工作流模型）
# ═══════════════════════════════════════════════════════════════════

@router.get("/ai")
async def get_ai_config():
    """读取 AI 配置（兼容旧结构：返回 chat 工作流模型的信息）。"""
    try:
        data = _read_models_data()
        models = data.get("models") or []
        wf = data.get("workflows") or {}
        chat_name = wf.get("chat") or (models[0]["name"] if models else "default")
        m = next((x for x in models if x.get("name") == chat_name), models[0] if models else {})
        return JSONResponse({
            "model": m.get("model", ""),
            "endpoint": m.get("base_url", ""),
            "api_key": m.get("api_key", ""),
        })
    except Exception:
        return JSONResponse({"model": "", "endpoint": "", "api_key": ""})


@router.post("/ai")
async def set_ai_config(body: dict[str, str]):
    """保存 AI 配置（兼容：更新 chat 工作流模型；无模型库时创建 default 模型）。"""
    try:
        data = _read_models_data()
        models = data.get("models") or []
        if not models:
            models = [{"name": "default", "base_url": "", "api_key": "", "model": "", "thinking": False}]
        m = models[0]
        m["base_url"] = body.get("endpoint", m.get("base_url", ""))
        m["api_key"] = body.get("api_key", m.get("api_key", ""))
        m["model"] = body.get("model", m.get("model", ""))
        data["models"] = models
        wf = data.get("workflows") or {}
        if not wf.get("chat"):
            wf["chat"] = m["name"]
        if not wf.get("utility"):
            wf["utility"] = m["name"]
        data["workflows"] = wf
        _write_models_data(data)
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.exception("保存 AI 配置失败")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/qqbot")
async def get_qqbot_config():
    """读取 QQ Bot 配置（从 config.toml 的 [[qq_bots]] 段）。"""
    try:
        p = _find_config_toml()
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        bots = data.get("qq_bots", [])
        if bots and isinstance(bots, list) and len(bots) > 0:
            bot = bots[0]
            return JSONResponse({"app_id": str(bot.get("id", ""))})
        return JSONResponse({})
    except Exception:
        return JSONResponse({})


@router.get("/qqbot/status")
async def get_qqbot_status():
    """查询 QQ Bot 当前状态：是否已配置、是否已注册适配器。"""
    try:
        p = _find_config_toml()
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        bots = data.get("qq_bots", [])
        configured = bool(bots and bots[0].get("id") and bots[0].get("secret"))

        # 检查适配器是否已注册
        running = False
        try:
            import nonebot
            driver = nonebot.get_driver()
            from nonebot.adapters.qq import Adapter as QQAdapter
            running = any(isinstance(a, QQAdapter) for a in driver._adapters.values())
        except Exception:
            pass

        return JSONResponse({
            "configured": configured,
            "running": running,
            "note": "配置更新后需重启服务生效" if configured and not running else "",
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/chat")
async def get_chat_history(before: str = "", limit: int = 50):
    """获取聊天记录。before 为消息 id（不传则取最新）。"""
    try:
        from pathlib import Path as _P
        from server.deps import get_config
        root = _P(get_config().game_dir)
        if before:
            msgs = _db.chat_before(root, int(before), limit=limit)
        else:
            msgs = _db.chat_recent(root, limit=limit)
        return JSONResponse({"messages": msgs})
    except Exception as e:
        return JSONResponse({"messages": [], "error": str(e)})


# ═══════════════════════════════════════════════════════════════════
# QQ Bot QR 扫码绑定（纯标准库，无外部依赖）
# ═══════════════════════════════════════════════════════════════════

import urllib.request
import urllib.error

def _qq_api_post(url: str, body: dict) -> dict:
    """同步 POST JSON，返回解析后的 dict。

    显式禁用系统代理（ProxyHandler({})）：QQ Bot 开放平台为国内服务，必须直连。
    若继承系统 HTTPS_PROXY（如 Clash 等代理软件 127.0.0.1:7890），TLS 链路易被
    代理中断，表现为 SSL: UNEXPECTED_EOF_WHILE_READING / WinError 10053。
    """
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            # q.qq.com 必需：缺 Accept: application/json 会返回 JS 反爬页面
            "Accept": "application/json",
            "User-Agent": "QQBotAdapter/ATRPG (Python; windows)",
        },
        method="POST",
    )
    # 不读环境变量代理，强制直连
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"retcode": -1, "msg": f"HTTP {e.code} {e.reason}"}
    except Exception as e:
        # TLS 中断/超时/DNS 等网络错误也返回结构化结果，避免冒泡成 500
        return {"retcode": -1, "msg": f"网络错误: {e}"}


@router.post("/qqbot/qr/start")
async def qqbot_qr_start():
    """创建 QQ Bot 绑定任务，返回二维码 URL。"""
    global _qr_state

    import base64, os
    aes_key = base64.b64encode(os.urandom(32)).decode()

    data = _qq_api_post(
        # 注意：必须是 q.qq.com/lite/create_bind_task（oau.q.qq.com 域名不存在）
        "https://q.qq.com/lite/create_bind_task",
        {"key": aes_key},
    )
    if data.get("retcode") != 0:
        return JSONResponse({"error": data.get("msg", "创建失败")}, status_code=500)

    task_id = data.get("data", {}).get("task_id")
    if not task_id:
        return JSONResponse({"error": "未获取到 task_id"}, status_code=500)

    qr_url = f"https://q.qq.com/qqbot/openclaw/connect.html?task_id={task_id}&_wv=2"

    _qr_state = {
        "task_id": task_id,
        "aes_key": aes_key,
        "status": "pending",
        "app_id": "",
        "secret": "",
        "user_openid": "",
    }

    logger.info(f"QQ Bot QR: task_id={task_id}")
    return JSONResponse({"qr_url": qr_url})


@router.get("/qqbot/qr/status")
async def qqbot_qr_status():
    """查询 QR 绑定状态。"""
    global _qr_state

    task_id = _qr_state.get("task_id")
    if not task_id:
        return JSONResponse({"status": "idle"})

    if _qr_state["status"] == "completed":
        return JSONResponse({"status": "completed", "app_id": _qr_state["app_id"]})

    data = _qq_api_post(
        "https://q.qq.com/lite/poll_bind_result",
        {"task_id": task_id},
    )
    if data.get("retcode") != 0:
        return JSONResponse({"status": "pending"})

    d = data.get("data", {})
    status_code = d.get("status", 0)

    if status_code == 2:  # completed
        app_id = str(d.get("bot_appid", ""))
        encrypted = d.get("bot_encrypt_secret", "")
        user_openid = d.get("user_openid", "")

        # 解密（AES-256-GCM：IV 12B | ciphertext | tag 16B，与 SDK 一致）
        try:
            import base64
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = base64.b64decode(_qr_state["aes_key"])
            raw = base64.b64decode(encrypted)
            iv, ct_with_tag = raw[:12], raw[12:]
            secret = AESGCM(key).decrypt(iv, ct_with_tag, None).decode("utf-8")
        except Exception:
            secret = encrypted

        _qr_state.update({
            "status": "completed",
            "app_id": app_id,
            "secret": secret,
            "user_openid": user_openid,
        })

        # 持久化
        cfg = _get_web_config()
        p = Path(cfg.game_dir) / ".atrpg" / "qqbot.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "app_id": app_id,
            "client_secret": secret,
            "user_openid": user_openid,
        }, ensure_ascii=False), encoding="utf-8")

        logger.info(f"QQ Bot 绑定成功: app_id={app_id}")
        return JSONResponse({"status": "completed", "app_id": app_id})

    if status_code == 3:
        _qr_state["status"] = "expired"
        return JSONResponse({"status": "expired"})

    return JSONResponse({"status": "pending"})
