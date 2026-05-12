/**
 * 统一页面骨架（Spec 18 §5.1）
 *
 * 替代原有的 MainLayout + AdminSidebarLayout 双布局方案。
 *
 * 结构：
 *   AppHeader（顶部栏）
 *   AppSidebar（5 域侧边栏）
 *   <Outlet />（内容区）
 *
 * P0 约束：
 * - 响应式断点：>= 1280px 展开，768~1279px 折叠，< 768px 隐藏
 * - 折叠状态通过 localStorage 'mulan-sidebar-collapsed' 持久化
 */
import { useState, useEffect, useCallback } from 'react';
import { Outlet } from 'react-router-dom';
import AppHeader from './AppHeader';
import AppSidebar from './AppSidebar';
import PageSkeleton from './PageSkeleton';
import { Suspense } from 'react';
import { STORAGE_KEY_SIDEBAR_COLLAPSED } from '../../config/menu';
import HelpAgentDrawer from '../../pages/agents/help-agent/HelpAgentDrawer';

export default function AppShellLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY_SIDEBAR_COLLAPSED);
      return stored === 'true';
    } catch {
      return false;
    }
  });

  const [mobileOpen, setMobileOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  // 持久化折叠状态
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY_SIDEBAR_COLLAPSED, String(sidebarCollapsed));
    } catch (_err) {
      // ignore localStorage write failures
    }
  }, [sidebarCollapsed]);

  // 响应式控制：< 768px 移动端通过 hamburger 切换
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);

  useEffect(() => {
    const handler = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (!mobile) setMobileOpen(false);
    };
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  const toggleSidebar = useCallback(() => {
    if (isMobile) {
      setMobileOpen((o) => !o);
    } else {
      setSidebarCollapsed((c) => !c);
    }
  }, [isMobile]);

  // ⌘+\ 快捷键收起/展开侧边栏
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === '\\') {
        e.preventDefault();
        toggleSidebar();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [toggleSidebar]);

  return (
    <div className="flex h-screen bg-slate-50">
      {/* 移动端 overlay */}
      {isMobile && mobileOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-20"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* 侧边栏 */}
      {(isMobile ? mobileOpen : true) && (
        <AppSidebar
          collapsed={isMobile ? false : sidebarCollapsed}
          onToggleCollapse={toggleSidebar}
        />
      )}

      {/* 主内容区 */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        {/* 顶部栏（含移动端 hamburger） */}
        <div className="shrink-0">
          {isMobile && (
            <button
              onClick={toggleSidebar}
              className="fixed bottom-4 right-4 z-30 w-12 h-12 bg-blue-600 text-white rounded-full shadow-lg flex items-center justify-center"
            >
              <i className="ri-menu-line text-xl" />
            </button>
          )}
          <AppHeader />
        </div>

        {/* 页面内容（Suspense 边界提供骨架屏） */}
        <main className="flex-1 overflow-auto min-h-0">
          <Suspense fallback={<PageSkeleton />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <button
        type="button"
        onClick={() => setHelpOpen(true)}
        className={`fixed ${isMobile ? 'bottom-20 right-4' : 'bottom-5 right-5'} z-30 w-11 h-11 rounded-full bg-slate-900 text-white shadow-lg flex items-center justify-center hover:bg-slate-800`}
        title="打开 Help Agent"
        aria-label="打开 Help Agent"
      >
        <i className="ri-question-answer-line text-lg" />
      </button>
      <HelpAgentDrawer open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  );
}
