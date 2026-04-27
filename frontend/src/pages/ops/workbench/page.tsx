/**
 * OpsWorkbench — 运维工作台（Spec 20）
 *
 * Split-Pane 统一入口：问数 / 资产 / 健康
 *
 * 布局：
 *   左侧面板（sidebar, 可拖拽调整宽度）：模式切换 + 上下文导航
 *   右侧面板（主内容区）：根据选中模式渲染 QueryPanel / AssetPanel / HealthPanel
 *
 * 快捷键：
 *   Ctrl/Cmd + 1  切换问数模式
 *   Ctrl/Cmd + 2  切换资产模式
 *   Ctrl/Cmd + 3  切换健康模式
 *
 * URL: /ops/workbench?mode=query|assets|health
 */
import { useState, useEffect, useCallback, useRef, lazy, Suspense } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { useAuth } from '../../../context/AuthContext';
import { ScopeProvider, useScope } from '../../home/context/ScopeContext';
import { ScopePicker } from '../../home/components/ScopePicker';
import { AssetInspectorDrawer } from '../../home/components/AssetInspectorDrawer';

// Lazy load panels
const QueryPanel = lazy(() =>
  import('./QueryPanel').then(m => ({ default: m.QueryPanel }))
);
const AssetPanel = lazy(() =>
  import('./AssetPanel').then(m => ({ default: m.AssetPanel }))
);
const HealthPanel = lazy(() =>
  import('./HealthPanel').then(m => ({ default: m.HealthPanel }))
);

// ── 类型定义 ──────────────────────────────────────────────────────
type WorkbenchMode = 'query' | 'assets' | 'health';

interface ModeConfig {
  key: WorkbenchMode;
  label: string;
  icon: string;
  shortcut: string;
  description: string;
}

const MODES: ModeConfig[] = [
  { key: 'query',  label: '问数',  icon: 'ri-question-answer-line', shortcut: '1', description: '自然语言查询数据' },
  { key: 'assets', label: '资产',  icon: 'ri-stack-line',           shortcut: '2', description: '浏览 Tableau 资产' },
  { key: 'health', label: '健康',  icon: 'ri-heart-pulse-line',     shortcut: '3', description: '资产健康检查' },
];

const VALID_MODES = new Set<WorkbenchMode>(['query', 'assets', 'health']);
const DEFAULT_MODE: WorkbenchMode = 'query';

const MIN_SIDEBAR_WIDTH = 200;
const MAX_SIDEBAR_WIDTH = 400;
const DEFAULT_SIDEBAR_WIDTH = 260;
const SIDEBAR_WIDTH_KEY = 'mulan-ops-workbench-sidebar-width';

// ── 主组件 ────────────────────────────────────────────────────────
function OpsWorkbenchInner() {
  const { user, hasPermission } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  // URL 状态
  const modeParam = searchParams.get('mode') as WorkbenchMode | null;
  const activeMode: WorkbenchMode = modeParam && VALID_MODES.has(modeParam) ? modeParam : DEFAULT_MODE;
  const assetId = searchParams.get('asset');
  const assetTab = searchParams.get('tab') ?? undefined;

  // 侧边栏宽度（持久化到 localStorage）
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    try {
      const stored = localStorage.getItem(SIDEBAR_WIDTH_KEY);
      if (stored) {
        const val = Number(stored);
        if (val >= MIN_SIDEBAR_WIDTH && val <= MAX_SIDEBAR_WIDTH) return val;
      }
    } catch { /* ignore */ }
    return DEFAULT_SIDEBAR_WIDTH;
  });

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
    } catch { /* ignore */ }
  }, [sidebarWidth]);

  // ── 拖拽调整宽度 ──────────────────────────────────────────────
  const isDragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    isDragging.current = true;
    startX.current = e.clientX;
    startWidth.current = sidebarWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const delta = ev.clientX - startX.current;
      const newWidth = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, startWidth.current + delta));
      setSidebarWidth(newWidth);
    };

    const handleUp = () => {
      isDragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
    };

    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
  }, [sidebarWidth]);

  // ── 模式切换 ──────────────────────────────────────────────────
  const setMode = useCallback((mode: WorkbenchMode) => {
    const next = new URLSearchParams(searchParams);
    next.set('mode', mode);
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  // ── 资产抽屉 ──────────────────────────────────────────────────
  const openAsset = useCallback((id: string, tab?: string) => {
    const next = new URLSearchParams(searchParams);
    next.set('asset', id);
    if (tab) next.set('tab', tab);
    else next.delete('tab');
    setSearchParams(next, { replace: false });
  }, [searchParams, setSearchParams]);

  const closeAsset = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    next.delete('asset');
    next.delete('tab');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  // ── 键盘快捷键 ───────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isMod = e.metaKey || e.ctrlKey;
      if (!isMod) return;

      if (e.key === '1') { e.preventDefault(); setMode('query'); }
      if (e.key === '2') { e.preventDefault(); setMode('assets'); }
      if (e.key === '3') { e.preventDefault(); setMode('health'); }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [setMode]);

  // ── 未登录态 ──────────────────────────────────────────────────
  if (!user) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="bg-white rounded-xl border border-slate-200 p-10 w-full max-w-md text-center">
          <h1 className="text-xl font-bold text-slate-800 mb-4">请先登录</h1>
          <Link
            to="/login"
            className="inline-block px-6 py-2.5 bg-blue-700 text-white rounded-lg text-sm font-semibold hover:bg-blue-800 transition-colors"
          >
            去登录
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-white">
      {/* 顶栏：ScopePicker */}
      <header className="shrink-0 border-b border-slate-200 bg-white px-4 py-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
              <i className="ri-dashboard-3-line text-blue-500" />
              运维工作台
            </h1>
            <span className="text-slate-200">|</span>
            <ScopePicker variant="default" />
          </div>
          <div className="flex items-center gap-2">
            <Link
              to="/"
              className="text-xs text-slate-500 hover:text-slate-700 flex items-center gap-1 px-2 py-1 rounded hover:bg-slate-100 transition-colors"
            >
              <i className="ri-home-4-line" />
              首页
            </Link>
          </div>
        </div>
      </header>

      {/* 主体：Split-Pane */}
      <div className="flex flex-1 min-h-0">
        {/* 左侧面板 */}
        <aside
          className="shrink-0 border-r border-slate-200 bg-slate-50 flex flex-col"
          style={{ width: sidebarWidth }}
        >
          {/* 模式切换 */}
          <nav className="p-3 space-y-1">
            {MODES.map(mode => {
              const isActive = activeMode === mode.key;
              // 资产/健康模式需要 tableau 权限
              const needPermission = mode.key === 'assets' || mode.key === 'health';
              const hasAccess = !needPermission || hasPermission('tableau');

              if (!hasAccess) return null;

              return (
                <button
                  key={mode.key}
                  onClick={() => setMode(mode.key)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                    isActive
                      ? 'bg-white text-slate-800 shadow-sm border border-slate-200'
                      : 'text-slate-600 hover:bg-white/60 hover:text-slate-800'
                  }`}
                  title={`切换到${mode.label}模式 (Ctrl+${mode.shortcut})`}
                >
                  <i className={`${mode.icon} text-base ${isActive ? 'text-blue-500' : 'text-slate-400'}`} />
                  <div className="flex-1 text-left">
                    <div className="font-medium">{mode.label}</div>
                    <div className="text-[11px] text-slate-400">{mode.description}</div>
                  </div>
                  <kbd className="text-[10px] text-slate-300 bg-slate-100 px-1.5 py-0.5 rounded">
                    {mode.shortcut}
                  </kbd>
                </button>
              );
            })}
          </nav>

          {/* 分隔线 */}
          <div className="border-t border-slate-200 mx-3" />

          {/* 模式特定的侧边栏内容 */}
          <div className="flex-1 overflow-y-auto p-3">
            {activeMode === 'query' && <QuerySidebar />}
            {activeMode === 'assets' && <AssetSidebar />}
            {activeMode === 'health' && <HealthSidebar />}
          </div>
        </aside>

        {/* 拖拽手柄 */}
        <div
          className="w-1 cursor-col-resize hover:bg-blue-300 active:bg-blue-400 transition-colors shrink-0"
          onMouseDown={handleDragStart}
          title="拖拽调整面板宽度"
        />

        {/* 右侧内容区 */}
        <main className="flex-1 min-w-0 bg-white">
          <Suspense
            fallback={
              <div className="flex items-center justify-center h-full text-slate-400 text-sm">
                <i className="ri-loader-4-line animate-spin mr-2" />
                加载中...
              </div>
            }
          >
            {activeMode === 'query' && <QueryPanel />}
            {activeMode === 'assets' && (
              <AssetPanel onSelectAsset={(id) => openAsset(id)} />
            )}
            {activeMode === 'health' && (
              <HealthPanel onOpenAsset={openAsset} />
            )}
          </Suspense>
        </main>
      </div>

      {/* 资产检查器抽屉 */}
      {hasPermission('tableau') && (
        <AssetInspectorDrawer
          assetId={assetId}
          tab={assetTab}
          onClose={closeAsset}
        />
      )}
    </div>
  );
}

// ── 侧边栏子组件 ──────────────────────────────────────────────────

/** 问数模式侧边栏：最近会话 */
function QuerySidebar() {
  return (
    <div className="space-y-3">
      <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">最近会话</h4>
      <div className="space-y-1">
        <p className="text-xs text-slate-400 py-4 text-center">暂无会话记录</p>
      </div>
      <button
        className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-xs text-blue-600
                   bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
      >
        <i className="ri-add-line" />
        新建查询
      </button>
    </div>
  );
}

/** 资产模式侧边栏：资产类型筛选 */
function AssetSidebar() {
  const { connectionId } = useScope();

  return (
    <div className="space-y-3">
      <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">数据源</h4>
      {!connectionId && (
        <p className="text-xs text-slate-400 py-2">请先选择连接</p>
      )}
      {connectionId && (
        <div className="space-y-1">
          <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-600 rounded hover:bg-white transition-colors cursor-pointer">
            <i className="ri-file-chart-line text-blue-500" />
            工作簿
          </div>
          <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-600 rounded hover:bg-white transition-colors cursor-pointer">
            <i className="ri-dashboard-line text-purple-500" />
            仪表板
          </div>
          <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-600 rounded hover:bg-white transition-colors cursor-pointer">
            <i className="ri-bar-chart-box-line text-emerald-500" />
            视图
          </div>
          <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-slate-600 rounded hover:bg-white transition-colors cursor-pointer">
            <i className="ri-database-2-line text-orange-500" />
            数据源
          </div>
        </div>
      )}

      <div className="border-t border-slate-200 pt-3">
        <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">搜索</h4>
        <div className="relative">
          <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-xs" />
          <input
            type="text"
            placeholder="搜索资产..."
            className="w-full pl-8 pr-3 py-1.5 text-xs border border-slate-200 rounded-lg
                       bg-white focus:outline-none focus:border-blue-300 transition-colors"
          />
        </div>
      </div>
    </div>
  );
}

/** 健康模式侧边栏：健康分类 */
function HealthSidebar() {
  return (
    <div className="space-y-3">
      <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">健康分类</h4>
      <div className="space-y-1">
        <div className="flex items-center justify-between px-2 py-1.5 text-xs text-slate-600 rounded hover:bg-white transition-colors cursor-pointer">
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-red-500" />
            差
          </span>
        </div>
        <div className="flex items-center justify-between px-2 py-1.5 text-xs text-slate-600 rounded hover:bg-white transition-colors cursor-pointer">
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-500" />
            警告
          </span>
        </div>
        <div className="flex items-center justify-between px-2 py-1.5 text-xs text-slate-600 rounded hover:bg-white transition-colors cursor-pointer">
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-500" />
            良好
          </span>
        </div>
        <div className="flex items-center justify-between px-2 py-1.5 text-xs text-slate-600 rounded hover:bg-white transition-colors cursor-pointer">
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            优秀
          </span>
        </div>
      </div>

      <div className="border-t border-slate-200 pt-3">
        <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">快捷操作</h4>
        <div className="space-y-1">
          <button className="w-full text-left px-2 py-1.5 text-xs text-slate-600 rounded hover:bg-white transition-colors flex items-center gap-2">
            <i className="ri-refresh-line text-slate-400" />
            刷新健康数据
          </button>
          <button className="w-full text-left px-2 py-1.5 text-xs text-slate-600 rounded hover:bg-white transition-colors flex items-center gap-2">
            <i className="ri-download-line text-slate-400" />
            导出报告
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 导出：包裹 ScopeProvider ────────────────────────────────────────
export default function OpsWorkbenchPage() {
  return (
    <ScopeProvider>
      <OpsWorkbenchInner />
    </ScopeProvider>
  );
}
