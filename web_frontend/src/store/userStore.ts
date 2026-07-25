/** 用户身份状态管理（Zustand）。 */

import { create } from "zustand";

export interface UserInfo {
  provider: string;
  openid: string;
  display_name: string;
  character_slug: string | null;
  permission: string;
  joined: string;
  is_admin: boolean;
}

export interface UserState {
  user: UserInfo | null;
  loading: boolean;
  error: string | null;
  initialized: boolean;

  setUser: (user: UserInfo | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setInitialized: () => void;
}

export const useUserStore = create<UserState>((set) => ({
  user: null,
  loading: true,
  error: null,
  initialized: false,

  setUser: (user) => set({ user, loading: false, error: null }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error, loading: false }),
  setInitialized: () => set({ initialized: true }),
}));