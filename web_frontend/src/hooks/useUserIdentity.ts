/** useUserIdentity — 用户身份 Hook。

首次访问时，向服务器请求分配一个用户 ID（POST /api/users/assign），
存入 localStorage。后续访问直接用已有 ID 去 /api/users/register 登录。

存储结构（localStorage）：
  atrpg_user = { provider: "web", id: "..." }
*/

import { useEffect, useCallback } from "react";
import { useUserStore, type UserInfo } from "../store/userStore";

const STORAGE_KEY = "atrpg_user";

interface StoredUser {
  provider: string;
  id: string;
  /** 兼容旧版 openid 字段 */
  openid?: string;
}

function getStoredUser(): StoredUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return {
      provider: String(parsed.provider || ""),
      id: String(parsed.id || parsed.openid || ""),
    };
  } catch {
    return null;
  }
}

function setStoredUser(user: StoredUser): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ provider: user.provider, id: user.id }));
}

export function useUserIdentity() {
  const { user, loading, error, initialized, setUser, setLoading, setError, setInitialized } = useUserStore();

  const init = useCallback(async () => {
    setLoading(true);
    try {
      let stored = getStoredUser();

      if (!stored) {
        const r = await fetch("/api/users/assign", { method: "POST" });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        stored = { provider: data.provider, id: data.id };
        setStoredUser(stored);
        setUser(data as UserInfo);
        return;
      }

      const r = await fetch("/api/users/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: stored.provider, id: stored.id }),
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
          `/api/users/${stored.provider}/${stored.id}/bind`,
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
          `/api/users/${stored.provider}/${stored.id}/display-name`,
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
    userId: user?.id || getStoredUser()?.id || "",
    provider: user?.provider || getStoredUser()?.provider || "",
    bindCharacter,
    updateDisplayName,
  };
}
