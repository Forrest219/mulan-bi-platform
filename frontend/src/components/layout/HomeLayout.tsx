/**
 * HomeLayout — 首页专用布局
 *
 * 结构：
 *   左侧 ConversationBar（260px，可折叠）
 *   右侧 <Outlet />（主内容区）
 *
 * 折叠状态持久化到 localStorage key: 'mulan-home-sidebar-collapsed'
 * 折叠动画：transition-all duration-200
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { ConversationBar } from '../../pages/home/components/ConversationBar';
import { useConversations } from '../../store/conversationStore';

const STORAGE_KEY = 'mulan-home-sidebar-collapsed';
const SIDEBAR_WIDTH = 260;

export default function HomeLayout() {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true';
    } catch {
      return false;
    }
  });

  const { addConversation } = useConversations();
  const navigate = useNavigate();

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed));
    } catch {
      /* localStorage not available — silently ignore */
    }
  }, [collapsed]);

  // 全局快捷键（P2-4）
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isMod = e.metaKey || e.ctrlKey;
      if (isMod && e.key === 'n') {
        e.preventDefault();
        addConversation().then((id) => navigate(`/chat/${id}`));
      }
      if (isMod && e.key === 'k') {
        e.preventDefault();
        // 聚焦 AskBar：通过 data-askbar-input 属性定位
        const el = document.querySelector<HTMLTextAreaElement>('[data-askbar-input]');
        el?.focus();
      }
      // Escape 键仅由 AskBar 自身处理，不在此处折叠侧边栏
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [addConversation, navigate]);

  const handleToggleCollapse = useCallback(() => setCollapsed((c) => !c), []);

  return (
    <div
      className="flex flex-row h-screen bg-white dark:bg-[#171717] text-gray-900 dark:text-gray-200"
      style={{ '--sidebar-width': collapsed ? '0px' : '260px' } as React.CSSProperties}
    >
      <ConversationBar collapsed={collapsed} onToggleCollapse={handleToggleCollapse} />

      <div
        className="w-full flex-1 min-w-0 transition-[margin-left] duration-300"
        style={{ marginLeft: collapsed ? 0 : 'var(--sidebar-width)' }}
      >
        {collapsed && (
          <button
            onClick={handleToggleCollapse}
            title="展开侧边栏"
            aria-label="展开侧边栏"
            className="fixed top-1/2 -translate-y-1/2 left-0 z-50 w-6 h-12 flex items-center justify-center bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-r-lg shadow-md transition-colors"
          >
            <i className="ri-sidebar-fold-line text-gray-500 dark:text-gray-400 text-sm" />
          </button>
        )}
        <Outlet />
      </div>
    </div>
  );
}
