"""config_routes.py --- /api/config/* AI 接口与 QQ Bot 配置。"""

from __future__ import annotations

import json
import logging
import re
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
# AI 配置（读/写项目根 config.toml 的 [atrpg] 段）
# ═══════════════════════════════════════════════════════════════════

@router.get("/ai")
async def get_ai_config():
    """读取 AI 配置。"""
    try:
        p = _find_config_toml()
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        atrpg = data.get("atrpg", {})
        return JSONResponse({
            "model": atrpg.get("llm_model", ""),
            "endpoint": atrpg.get("llm_base_url", ""),
            "api_key": atrpg.get("llm_api_key", ""),
        })
    except Exception:
        return JSONResponse({"model": "", "endpoint": "", "api_key": ""})


@router.post("/ai")
async def set_ai_config(body: dict[str, str]):
    """保存 AI 配置到 config.toml（更新 [atrpg] 段）。"""
    try:
        p = _find_config_toml()
        raw = p.read_text(encoding="utf-8")

        def _set_key(section: str, key: str, value: str) -> str:
            """在 TOML 中设定某 key 的值。"""
            pattern = rf'^(\s*{key}\s*=\s*").*?("\s*)$'
            new_line = f'{key} = "{value}"'
            if re.search(pattern, raw, flags=re.MULTILINE):
                return re.sub(pattern, new_line, raw, flags=re.MULTILINE)
            # key 不存在：追加到 section 末尾
            lines = raw.split("\n")
            result_lines = []
            in_section = False
            inserted = False
            for i, line in enumerate(lines):
                result_lines.append(line)
                if line.strip().startswith(f"[{section}]"):
                    in_section = True
                    continue
                if in_section and (line.strip().startswith("[") or i == len(lines) - 1):
                    if not inserted:
                        if i == len(lines) - 1:
                            result_lines.append(new_line)
                        else:
                            result_lines.insert(-1, new_line)
                        inserted = True
                    in_section = False
            return "\n".join(result_lines)

        raw = _set_key("atrpg", "llm_base_url", body.get("endpoint", ""))
        raw = _set_key("atrpg", "llm_api_key", body.get("api_key", ""))
        raw = _set_key("atrpg", "llm_model", body.get("model", ""))

        p.write_text(raw, encoding="utf-8")
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
    """同步 POST JSON，返回解析后的 dict。"""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "ATRPG/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


@router.post("/qqbot/qr/start")
async def qqbot_qr_start():
    """创建 QQ Bot 绑定任务，返回二维码 URL。"""
    global _qr_state

    import base64, os
    aes_key = base64.b64encode(os.urandom(32)).decode()

    data = _qq_api_post(
        "https://oau.q.qq.com/oauth/bind/task/create",
        {"key": aes_key},
    )
    if data.get("retcode") != 0:
        return JSONResponse({"error": data.get("msg", "创建失败")}, status_code=500)

    task_id = data.get("data", {}).get("task_id")
    if not task_id:
        return JSONResponse({"error": "未获取到 task_id"}, status_code=500)

    qr_url = f"https://q.qq.com/openid-connect/scan?task_id={task_id}"

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
        "https://oau.q.qq.com/oauth/bind/result",
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

        # 解密
        try:
            import base64
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
            key = base64.b64decode(_qr_state["aes_key"])
            ct = base64.b64decode(encrypted)
            cipher = AES.new(key, AES.MODE_ECB)
            secret = unpad(cipher.decrypt(ct), 16).decode()
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
