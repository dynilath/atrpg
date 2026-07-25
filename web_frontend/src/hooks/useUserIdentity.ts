/** useUserIdentity — 用户身份 Hook。

首次访问时，向服务器请求分配一个用户 ID（POST /api/users/assign），
存入 localStorage。后续访问直接用已有 ID 去 /api/users/register 登录。
对于 QQ 等外部来源，使用 provider=qq + 平台 openid 标记。

存储结构（localStorage）：
  atrpg_user = { provider: "web", openid: "..." }
*/

import { useEffect, useCallback } from "react";
import { useUserStore, UserInfo } from "../store/userStore";

const STORAGE_KEY = "atrpg_user";

interface StoredUser {
  provider: string;
  openid: string;
}

function getStoredUser(): StoredUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredUser;
  } catch {
    return null;
  }
}

function setStoredUser(user: StoredUser): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
}

export function useUserIdentity() {
  const { user, loading, error, initialized, setUser, setLoading, setError, setInitialized } = useUserStore();

  /** 初始化：无本地 ID → 找服务器分配；有本地 ID → 注册/登录 */
  const init = useCallback(async () => {
    setLoading(true);
    try {
      let stored = getStoredUser();

      // 没有本地 ID → 向服务器请求分配
      if (!stored) {
        const r = await fetch("/api/users/assign", { method: "POST" });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        stored = { provider: data.provider, openid: data.openid };
        setStoredUser(stored);
        setUser(data as UserInfo);
        return;
      }

      // 有本地 ID → 注册/登录
      const r = await fetch("/api/users/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(stored),
      });
      if (!r.ok) throw new Error(await r.text());
      const data: UserInfo = await r.json();
      setUser(data);
    } catch (e: any) {
      setError(e.message);
    }
  }, [setUser, setLoading, setError]);

  const bindCharacter = useCallback(
    async (characterSlug: string | null) => {
      const stored = getStoredUser();
      if (!stored) return;
      try {
        const r = await fetch(
          `/api/users/${stored.provider}/${stored.openid}/bind`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ character_slug: characterSlug || "" }),
          }
        );
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        if (user) {
          setUser({ ...user, character_slug: data.character_slug });
        }
      } catch (e: any) {
        setError(e.message);
      }
    },
    [user, setUser, setError]
  );

  const updateDisplayName = useCallback(
    async (name: string) => {
      const stored = getStoredUser();
      if (!stored) return;
      try {
        const r = await fetch(
          `/api/users/${stored.provider}/${stored.openid}/display-name`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ display_name: name }),
          }
        );
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        if (user) {
          setUser({ ...user, display_name: data.display_name });
        }
      } catch (e: any) {
        setError(e.message);
      }
    },
    [user, setUser, setError]
  );

  // 启动时初始化（仅一次）
  useEffect(() => {
    if (!initialized) {
      setInitialized();
      init();
    }
  }, [initialized, init, setInitialized]);

  return {
    user,
    loading,
    error,
    openid: user?.openid || getStoredUser()?.openid || "",
    provider: user?.provider || getStoredUser()?.provider || "",
    bindCharacter,
    updateDisplayName,
  };
}