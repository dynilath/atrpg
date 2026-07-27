/** 游戏状态管理（Zustand）。 */

import { create } from "zustand";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  sender?: string;
  character?: string;  // 角色 slug（仅已绑定角色的消息）
  source?: string;  // "web" | "qq" | "bot" | "system"
}

export interface SceneInfo {
  name: string;
  slug: string;
  description: string;
  attendees: string[];
}

export interface CharacterInfo {
  name: string;
  slug: string;
  identity: string;
  scene_slug: string;
}

export interface GameState {
  // 连接状态
  connected: boolean;
  sessionKey: string;

  // 角色
  character: CharacterInfo | null;
  hasPendingChar: boolean;

  // 场景
  scene: SceneInfo | null;

  // 消息
  messages: ChatMessage[];

  // 角色颜色映射: slug → color (hue 0-360)
  charColors: Record<string, number>;

  // 动作
  setConnected: (connected: boolean, sessionKey?: string) => void;
  setCharacter: (char: CharacterInfo | null) => void;
  setScene: (scene: SceneInfo | null) => void;
  addMessage: (msg: ChatMessage) => void;
  addMessages: (msgs: ChatMessage[]) => void;
  appendLastAssistant: (chunk: string) => void;
  clearMessages: () => void;
  setCharColors: (colors: Record<string, number>) => void;
}

export const useGameStore = create<GameState>((set, get) => ({
  connected: false,
  sessionKey: "",
  character: null,
  hasPendingChar: false,
  scene: null,
  messages: [],
  charColors: {},

  setConnected: (connected, sessionKey) =>
    set({ connected, sessionKey: sessionKey || get().sessionKey }),

  setCharacter: (character) => set({ character }),

  setScene: (scene) => set({ scene }),

  addMessage: (msg) =>
    set((s) => {
      if (s.messages.some((m) => m.id === msg.id)) return s;
      return { messages: [...s.messages, msg] };
    }),

  addMessages: (msgs) =>
    set((s) => {
      const existing = new Set(s.messages.map((m) => m.id));
      const newMsgs = msgs.filter((m) => !existing.has(m.id));
      return { messages: [...newMsgs, ...s.messages] };
    }),

  appendLastAssistant: (chunk) =>
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, content: last.content + chunk };
      } else {
        msgs.push({
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: chunk,
          timestamp: Date.now(),
        });
      }
      return { messages: msgs };
    }),

  clearMessages: () => set({ messages: [] }),
  setCharColors: (colors) => set({ charColors: colors }),
}));
