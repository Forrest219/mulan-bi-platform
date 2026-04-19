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
      className="flex min-h-screen bg-white"
      style={{ '--conv-bar-w': collapsed ? '0px' : '260px' } as React.CSSProperties}
    >
        {/* 左侧对话历史栏 */}
        <div
          className="shrink-0 transition-all duration-200 overflow-hidden"
          style={{ width: collapsed ? 0 : SIDEBAR_WIDTH }}
        >
          <div style={{ width: SIDEBAR_WIDTH }} className="h-full">
            <ConversationBar
              collapsed={collapsed}
              onToggleCollapse={handleToggleCollapse}
            />
          </div>
        </div>

        {/* 侧边栏折叠时，在左边缘渲染展开按钮（逃生门） */}
        {collapsed && (
          <button
            onClick={handleToggleCollapse}
            title="展开侧边栏"
            aria-label="展开侧边栏"
            className="fixed left-0 top-1/2 -translate-y-1/2 z-50
                       w-5 h-10 flex items-center justify-center
                       bg-white border border-l-0 border-slate-200
                       rounded-r-lg shadow-sm
                       text-slate-400 hover:text-slate-700 hover:bg-slate-50
                       transition-colors duration-150"
          >
            <i className="ri-arrow-right-s-line text-base" />
          </button>
        )}

        {/* 右侧主内容区 */}
        <div className="flex-1 min-w-0">
          <Outlet />
        </div>
      </div>
  );
}
