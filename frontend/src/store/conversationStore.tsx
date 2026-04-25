/**
 * conversationStore — 对话历史管理（React Context + useReducer）
 *
 * localStorage key: 'mulan_conversations'
 * schema: C2（Conversation + ConversationMessage）
 * 不引入 zustand，仅用原生 React API
 *
 * P1 变更：
 * - 初始化时调 GET /api/agent/conversations（Spec 36 §5），localStorage 作 fallback
 * - addConversation 本地创建（不调 API），由 SSE stream 的 metadata.conversation_id 驱动
 * - deleteConversation 先调后端 DELETE（/api/agent/conversations/{id}），成功后再移除 state
 * - appendMessage 只更新本地 state
 */
import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { conversationsApi } from '../api/conversations';
import { agentConversationsApi } from '../api/agent';

// ─── Types ───────────────────────────────────────────────────────────────────

export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string; // ISO 8601 UTC
  query_context?: unknown; // P2 预留，P0 写 undefined
}

export interface Conversation {
  id: string;
  title: string;        // 取首条消息前 20 字
  updated_at: string;   // ISO 8601 UTC
  messages: ConversationMessage[];
}

// ─── LocalStorage helpers ─────────────────────────────────────────────────────

const STORAGE_KEY = 'mulan_conversations';

function loadFromStorage(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveToStorage(conversations: Conversation[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
  } catch (_err) {
    // ignore localStorage write failures
  }
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function nowUtc(): string {
  return new Date().toISOString();
}

// ─── Reducer ──────────────────────────────────────────────────────────────────

type Action =
  | { type: 'LOAD'; payload: Conversation[] }
  | { type: 'ADD_CONVERSATION'; payload: Conversation }
  | { type: 'APPEND_MESSAGE'; payload: { conversationId: string; message: ConversationMessage } }
  | { type: 'DELETE_CONVERSATION'; payload: string }
  | { type: 'UPDATE_TITLE'; payload: { id: string; title: string } };

function reducer(state: Conversation[], action: Action): Conversation[] {
  switch (action.type) {
    case 'LOAD':
      return action.payload;

    case 'ADD_CONVERSATION':
      return [action.payload, ...state];

    case 'APPEND_MESSAGE': {
      const { conversationId, message } = action.payload;
      return state.map((conv) => {
        if (conv.id !== conversationId) return conv;
        const updatedMessages = [...conv.messages, message];
        // 更新 title（取首条消息前 20 字）
        const firstUserMsg = updatedMessages.find((m) => m.role === 'user');
        const newTitle = firstUserMsg
          ? firstUserMsg.content.slice(0, 20)
          : conv.title;
        return {
          ...conv,
          title: newTitle,
          updated_at: nowUtc(),
          messages: updatedMessages,
        };
      });
    }

    case 'DELETE_CONVERSATION':
      return state.filter((conv) => conv.id !== action.payload);

    case 'UPDATE_TITLE':
      return state.map((conv) =>
        conv.id === action.payload.id
          ? { ...conv, title: action.payload.title, updated_at: nowUtc() }
          : conv
      );

    default:
      return state;
  }
}

// ─── Context ──────────────────────────────────────────────────────────────────

interface ConversationContextValue {
  conversations: Conversation[];
  /** 是否正在从后端加载对话列表 */
  isLoading: boolean;
  /** 新增对话，返回新 id（异步，优先调后端） */
  addConversation: () => Promise<string>;
  /** 追加消息到指定对话 */
  appendMessage: (conversationId: string, message: Omit<ConversationMessage, 'id' | 'created_at'>) => void;
  /** 删除对话（异步，优先调后端） */
  deleteConversation: (id: string) => Promise<void>;
  /** 更新对话标题（异步，优先调后端） */
  updateConversationTitle: (id: string, title: string) => Promise<void>;
}

const ConversationContext = createContext<ConversationContextValue | null>(null);

// ─── Provider ─────────────────────────────────────────────────────────────────

export function ConversationProvider({ children }: { children: ReactNode }) {
  const [conversations, dispatch] = useReducer(reducer, [], loadFromStorage);
  const [isLoading, setIsLoading] = useState(true);

  // 初始化：先从后端拉取，失败则用 localStorage 数据
  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    agentConversationsApi
      .list()
      .then((list) => {
        if (cancelled) return;
        // 将后端列表映射为本地 Conversation 结构（messages 为空，按需加载）
        const mapped: Conversation[] = list.map((item) => ({
          id: item.id,
          title: item.title ?? '新对话',
          updated_at: item.updated_at,
          messages: [],
        }));
        dispatch({ type: 'LOAD', payload: mapped });
      })
      .catch(() => {
        // API 失败：保留 localStorage 已加载的数据，不覆盖
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 每次 state 变化后同步到 localStorage
  useEffect(() => {
    saveToStorage(conversations);
  }, [conversations]);

  const addConversation = useCallback(async (): Promise<string> => {
    try {
      const resp = await conversationsApi.create();
      const newConv: Conversation = {
        id: resp.id,
        title: resp.title,
        updated_at: resp.updated_at,
        messages: [],
      };
      dispatch({ type: 'ADD_CONVERSATION', payload: newConv });
      return resp.id;
    } catch {
      // 后端失败：纯本地创建
      const id = generateId();
      const newConv: Conversation = {
        id,
        title: '新对话',
        updated_at: nowUtc(),
        messages: [],
      };
      dispatch({ type: 'ADD_CONVERSATION', payload: newConv });
      return id;
    }
  }, []);

  const appendMessage = useCallback(
    (conversationId: string, message: Omit<ConversationMessage, 'id' | 'created_at'>) => {
      const fullMessage: ConversationMessage = {
        ...message,
        id: generateId(),
        created_at: nowUtc(),
      };
      dispatch({ type: 'APPEND_MESSAGE', payload: { conversationId, message: fullMessage } });
    },
    []
  );

  const deleteConversation = useCallback(async (id: string): Promise<void> => {
    try {
      // Spec 36 §5: DELETE /api/agent/conversations/{id}
      await agentConversationsApi.deleteConversation(id);
    } catch {
      // 忽略后端错误，仍然从本地移除
    }
    dispatch({ type: 'DELETE_CONVERSATION', payload: id });
  }, []);

  const updateConversationTitle = useCallback(async (id: string, title: string): Promise<void> => {
    // 乐观更新：先更新 UI
    dispatch({ type: 'UPDATE_TITLE', payload: { id, title } });
    try {
      await conversationsApi.update(id, title);
    } catch {
      // 后端失败时保留本地更新（容忍离线场景）
    }
  }, []);

  return (
    <ConversationContext.Provider
      value={{
        conversations,
        isLoading,
        addConversation,
        appendMessage,
        deleteConversation,
        updateConversationTitle,
      }}
    >
      {children}
    </ConversationContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useConversations(): ConversationContextValue {
  const ctx = useContext(ConversationContext);
  if (!ctx) {
    throw new Error('useConversations must be used within ConversationProvider');
  }
  return ctx;
}
