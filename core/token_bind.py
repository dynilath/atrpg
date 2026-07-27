"""token_bind.py --- QQ 群绑定令牌管理。

启动时生成随机 token（仅内存），在控制台输出。
QQ 群中 @bot 发送 token 即绑定当前游戏目录到该群。
使用后立即生成新 token（仅内存），原 token 失效。
群绑定结果持久化到 .atrpg/target_group。
"""

from __future__ import annotations

import logging
import secrets
import string
from pathlib import Path

logger = logging.getLogger("atrpg.bind")

TOKEN_LENGTH = 10
TOKEN_ALPHABET = string.ascii_letters + string.digits  # A-Za-z0-9

# 模块级内存变量：当前有效 token
_token: str | None = None


def _binding_path(game_dir: str | Path) -> Path:
    return Path(game_dir) / ".atrpg" / "target_group"


def _generate() -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))


def current_token(game_dir: str | Path) -> str:
    """返回当前有效的 token（仅在内存中，每次启动重新生成）。"""
    global _token
    if _token is None:
        _token = _generate()
    return _token


def bound_group(game_dir: str | Path) -> str:
    """读取已绑定的群 openid。无绑定返回空字符串。"""
    p = _binding_path(game_dir)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def try_bind(game_dir: str | Path, message: str, group_id: str) -> str | None:
    """检查消息是否匹配 token，匹配则绑定群并返回新 token。不匹配返回 None。"""
    global _token
    if _token is None:
        _token = _generate()

    if message.strip() != _token:
        return None

    # 绑定群（持久化）
    bp = _binding_path(game_dir)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(group_id, encoding="utf-8")

    # 立即更换 token（仅内存）
    old = _token
    _token = _generate()

    logger.info(f"群绑定成功: {group_id} -> {game_dir} (token {old[:4]}*** 已失效)")
    return _token
