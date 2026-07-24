"""console.py — 内嵌网页控制台。

在 NoneBot 的 FastAPI driver 上挂路由，提供 LLM 对话历史查看与回滚功能。
访问 http://127.0.0.1:8080/console/

路由：
  GET  /console/                              主页（单页 HTML+JS）
  GET  /console/api/sessions                  列出所有 session
  GET  /console/api/sessions/{sid}/turns      列出某 session 的轮次摘要
  GET  /console/api/sessions/{sid}/turns/{n}  某轮完整 messages
  POST /console/api/sessions/{sid}/rollback/{n}  回滚到某轮
"""

from __future__ import annotations

import json
from typing import Any

from nonebot import get_driver, logger


def get_store():
    """获取 Store 实例（与 gm.py 共享同一游戏目录）。"""
    from .gm import get_store as _gs
    return _gs()


def setup_console() -> None:
    """在 NoneBot 启动时挂载控制台路由到 FastAPI app。"""
    try:
        app = get_driver().server_app
    except (AttributeError, RuntimeError) as e:
        logger.warning(f"控制台未启用：driver 不支持 server_app（需 ~fastapi）：{e}")
        return

    from fastapi.responses import HTMLResponse, JSONResponse

    @app.get("/console/", response_class=HTMLResponse)
    async def console_page():
        return HTMLResponse(_PAGE_HTML)

    @app.get("/console/api/sessions")
    async def api_sessions():
        try:
            s = get_store()
            return JSONResponse(s.list_sessions())
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/console/api/sessions/{sid}/turns")
    async def api_turns(sid: str):
        try:
            s = get_store()
            return JSONResponse(s.list_turns(sid))
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/console/api/sessions/{sid}/usage")
    async def api_usage(sid: str):
        try:
            s = get_store()
            return JSONResponse(s.usage_summary(sid))
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/console/api/sessions/{sid}/turns/{turn_no}")
    async def api_turn_detail(sid: str, turn_no: int):
        try:
            s = get_store()
            d = s.get_turn_detail(sid, turn_no)
            if d is None:
                return JSONResponse({"error": "轮次不存在"}, status_code=404)
            return JSONResponse(d)
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/console/api/sessions/{sid}/rollback/{turn_no}")
    async def api_rollback(sid: str, turn_no: int):
        try:
            s = get_store()
            ok = s.rollback(sid, turn_no)
            if not ok:
                return JSONResponse({"error": "回滚失败（轮次不存在）"}, status_code=404)
            logger.info(f"控制台回滚: session={sid} turn={turn_no}")
            return JSONResponse({"ok": True, "rolled_back_to": turn_no})
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)}, status_code=500)

    logger.success("控制台已挂载: http://127.0.0.1:8080/console/")


# ---------------------------------------------------------------------------
# 单页 HTML（vanilla JS + CSS，不引入前端框架）
# ---------------------------------------------------------------------------

_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ATRPG 控制台</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
  header { background: #16213e; padding: 10px 20px; border-bottom: 1px solid #0f3460; }
  header h1 { font-size: 18px; color: #e94560; }
  .main { display: flex; flex: 1; overflow: hidden; }
  .sidebar { width: 380px; border-right: 1px solid #0f3460; overflow-y: auto; background: #16213e; }
  .detail { flex: 1; overflow-y: auto; padding: 16px; }
  .section-title { padding: 8px 12px; font-size: 13px; color: #8a8a9a; text-transform: uppercase; border-bottom: 1px solid #0f3460; position: sticky; top: 0; background: #16213e; z-index: 1; }
  .session-item { padding: 8px 12px; cursor: pointer; border-bottom: 1px solid #0f3460; font-size: 12px; }
  .session-item:hover { background: #0f3460; }
  .session-item.active { background: #0f3460; }
  .turn-item { padding: 8px 12px; border-bottom: 1px solid #0f3460; cursor: pointer; font-size: 12px; }
  .turn-item:hover { background: #0f3460; }
  .turn-item.active { background: #1a1a4e; border-left: 3px solid #e94560; }
  .turn-meta { color: #8a8a9a; font-size: 11px; margin-top: 2px; }
  .turn-preview { color: #c0c0d0; margin-top: 3px; line-height: 1.4; }
  .turn-reply { color: #53c0a0; margin-top: 2px; font-style: italic; }
  .turn-usage { color: #6080a0; font-size: 10px; margin-top: 2px; }
  .rollback-btn { float: right; background: #e94560; color: #fff; border: none; padding: 2px 8px; border-radius: 3px; cursor: pointer; font-size: 11px; }
  .rollback-btn:hover { background: #c81e45; }
  .msg { margin-bottom: 12px; border-radius: 6px; overflow: hidden; border: 1px solid #2a2a4e; }
  .msg-header { padding: 4px 10px; font-size: 12px; font-weight: bold; display: flex; justify-content: space-between; }
  .msg-body { padding: 8px 10px; font-size: 13px; white-space: pre-wrap; word-break: break-word; line-height: 1.5; }
  .msg-system .msg-header { background: #2d1b4e; } .msg-system .msg-body { background: #1e1530; }
  .msg-user .msg-header { background: #1b3a4e; } .msg-user .msg-body { background: #152e3a; }
  .msg-assistant .msg-header { background: #1b4e2d; } .msg-assistant .msg-body { background: #15301e; }
  .msg-tool .msg-header { background: #4e3a1b; } .msg-tool .msg-body { background: #3a2e15; }
  .tool-call { margin: 6px 0; padding: 6px 8px; background: #0a1a0e; border-left: 3px solid #53c0a0; border-radius: 3px; font-size: 12px; }
  .tool-call-name { color: #53c0a0; font-weight: bold; }
  .tool-call-args { color: #a0c0a0; margin-top: 3px; white-space: pre-wrap; word-break: break-word; }
  .msg-content-empty { color: #666; font-style: italic; }
  .loading { text-align: center; padding: 40px; color: #8a8a9a; }
  .empty { text-align: center; padding: 40px; color: #555; }
</style>
</head>
<body>
<header><h1>ATRPG 主持人控制台</h1></header>
<div class="main">
  <div class="sidebar">
    <div class="section-title">会话</div>
    <div id="sessions"><div class="loading">加载中...</div></div>
    <div class="section-title">轮次</div>
    <div id="turns"><div class="empty">请选择会话</div></div>
  </div>
  <div class="detail" id="detail">
    <div class="empty">请选择轮次查看详情</div>
  </div>
</div>
<script>
const API = '/console/api';
let currentSession = null;
let currentTurn = null;

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  return r.json();
}

async function loadSessions() {
  const data = await fetchJSON(`${API}/sessions`);
  const el = document.getElementById('sessions');
  if (!data || data.length === 0) {
    el.innerHTML = '<div class="empty">暂无会话</div>';
    return;
  }
  el.innerHTML = data.map(sid =>
    `<div class="session-item" onclick="selectSession('${sid}')">${sid}</div>`
  ).join('');
}

async function selectSession(sid) {
  currentSession = sid;
  currentTurn = null;
  document.querySelectorAll('.session-item').forEach(e => e.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('detail').innerHTML = '<div class="empty">请选择轮次查看详情</div>';
  const [data, usage] = await Promise.all([
    fetchJSON(`${API}/sessions/${sid}/turns`),
    fetchJSON(`${API}/sessions/${sid}/usage`),
  ]);
  const el = document.getElementById('turns');
  // 总计用量统计
  let summaryHtml = '';
  if (usage && !usage.error) {
    const hitRate = usage.prompt_tokens > 0 ? ((usage.cached_tokens / usage.prompt_tokens) * 100).toFixed(1) : '0';
    summaryHtml = `
      <div style="padding:8px 12px;background:#0f1a2e;border-bottom:1px solid #0f3460;font-size:11px;">
        <div style="color:#e94560;font-weight:bold;margin-bottom:4px;">总计用量</div>
        <div class="turn-usage">输入: ${usage.prompt_tokens} | 输出: ${usage.completion_tokens} | 缓存命中: ${usage.cached_tokens} (${hitRate}%)</div>
        <div class="turn-usage" style="margin-top:2px;">有统计轮次: ${usage.turns_with_usage}/${usage.turns_total}</div>
      </div>`;
  }
  if (!data || data.length === 0) {
    el.innerHTML = summaryHtml + '<div class="empty">暂无轮次</div>';
    return;
  }
  el.innerHTML = summaryHtml + data.map(t => {
    const u = t.usage || {};
    const hasUsage = u && u.prompt_tokens;
    const hitRate = hasUsage && u.prompt_tokens > 0 ? ((u.cached_tokens / u.prompt_tokens) * 100).toFixed(0) : '0';
    const usageHtml = hasUsage
      ? `<div class="turn-usage">↓${u.prompt_tokens} ↑${u.completion_tokens||0} 缓存${u.cached_tokens||0}(${hitRate}%)</div>`
      : `<div class="turn-usage" style="color:#555;">无用量数据</div>`;
    return `
    <div class="turn-item" onclick="selectTurn('${sid}', ${t.turn_no})">
      <button class="rollback-btn" onclick="rollback(event, '${sid}', ${t.turn_no})">回滚</button>
      <div>#${t.turn_no} <span class="turn-meta">${t.timestamp}</span></div>
      <div class="turn-meta">${t.sender || '未知'}</div>
      <div class="turn-preview">${esc(t.player_text).substring(0, 80)}</div>
      ${t.reply_preview ? `<div class="turn-reply">↳ ${esc(t.reply_preview).substring(0, 60)}</div>` : ''}
      ${usageHtml}
    </div>`;
  }).join('');
}

async function selectTurn(sid, turnNo) {
  currentTurn = turnNo;
  document.querySelectorAll('.turn-item').forEach(e => e.classList.remove('active'));
  event.target.closest('.turn-item').classList.add('active');
  document.getElementById('detail').innerHTML = '<div class="loading">加载中...</div>';
  const d = await fetchJSON(`${API}/sessions/${sid}/turns/${turnNo}`);
  if (d.error) {
    document.getElementById('detail').innerHTML = `<div class="empty">${esc(d.error)}</div>`;
    return;
  }
  const msgs = d.messages || [];
  const u = d.usage || {};
  const hasUsage = u && u.prompt_tokens;
  const hitRate = hasUsage && u.prompt_tokens > 0 ? ((u.cached_tokens / u.prompt_tokens) * 100).toFixed(1) : '0';
  const usageLine = hasUsage
    ? ` | ↓输入${u.prompt_tokens} ↑输出${u.completion_tokens||0} 缓存${u.cached_tokens||0}(${hitRate}%)`
    : ' | 无用量数据';
  document.getElementById('detail').innerHTML = `
    <div style="margin-bottom:12px;color:#8a8a9a;font-size:12px;">
      轮次 #${d.turn_no} | ${d.timestamp} | 发送人: ${esc(d.sender||'')}${usageLine}
      <button class="rollback-btn" onclick="rollback(null, '${sid}', ${d.turn_no})">回滚到此轮</button>
    </div>
    ${msgs.map(renderMsg).join('')}
  `;
}

function renderMsg(m) {
  const role = m.role || '';
  const content = m.content || '';
  let body = '';
  if (content && content.trim()) {
    body = `<div class="msg-body">${esc(content)}</div>`;
  } else {
    body = '<div class="msg-body msg-content-empty">（无文本内容）</div>';
  }
  // tool_calls 展开
  if (m.tool_calls && m.tool_calls.length > 0) {
    body += m.tool_calls.map(tc => {
      const name = tc.function?.name || '?';
      let args = tc.function?.arguments || '';
      try { args = JSON.stringify(JSON.parse(args), null, 2); } catch(e) {}
      return `<div class="tool-call"><span class="tool-call-name">🔧 ${esc(name)}</span><div class="tool-call-args">${esc(args)}</div></div>`;
    }).join('');
  }
  // tool result 的 tool_call_id
  let headerExtra = '';
  if (m.tool_call_id) headerExtra = ` <span style="color:#8a8a9a">${esc(m.tool_call_id.substring(0,20))}</span>`;
  return `<div class="msg msg-${role}"><div class="msg-header"><span>${role}${headerExtra}</span></div>${body}</div>`;
}

async function rollback(ev, sid, turnNo) {
  if (ev) ev.stopPropagation();
  if (!confirm(`确认回滚到轮次 #${turnNo}？\n该轮之后的对话将永久删除。`)) return;
  const r = await fetchJSON(`${API}/sessions/${sid}/rollback/${turnNo}`, { method: 'POST' });
  if (r.ok) {
    alert(`已回滚到轮次 #${turnNo}`);
    selectSession(sid);
  } else {
    alert('回滚失败: ' + (r.error || '未知错误'));
  }
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

loadSessions();
</script>
</body>
</html>
"""
