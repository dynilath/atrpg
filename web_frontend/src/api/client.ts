/** API 客户端封装。

自动附带用户身份 header（X-Provider / X-User-Id），供后端权限校验。
*/

const BASE = "";

export function authHeaders(): Record<string, string> {
  try {
    const raw = localStorage.getItem("atrpg_user");
    if (!raw) return {};
    const u = JSON.parse(raw);
    return {
      "X-Provider": u.provider || "",
      "X-User-Id": u.id || u.openid || "",
    };
  } catch {
    return {};
  }
}

export async function apiGet<T = unknown>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    headers: { ...authHeaders() },
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ error: r.statusText }));
    throw new Error(err.error || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function apiPost<T = unknown>(
  path: string,
  body: unknown
): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ error: r.statusText }));
    throw new Error(err.error || `HTTP ${r.status}`);
  }
  return r.json();
}
