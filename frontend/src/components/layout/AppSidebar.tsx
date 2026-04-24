/**
 * 5 域侧边栏组件（Spec 18 §5.3）
 *
 * P0 约束：
 * - 折叠态仅显示域图标，hover 显示 tooltip
 * - 域展开状态 + 折叠状态通过 localStorage 持久化
 * - disabled 菜单项 hover 显示 "功能开发中，敬请期待" tooltip
 */
import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import {
  menuConfig,
  type MenuDomain,
  type MenuItem,
  hasRoleLevel,
  STORAGE_KEY_DOMAIN_OPEN,
} from '../../config/menu';

const COLLAPSED_WIDTH = 56;
const EXPANDED_WIDTH = 240;

// ────────────────────────────────────────────────────────────
// 判断单个菜单项是否对当前用户可见
// ────────────────────────────────────────────────────────────
function isItemVisible(item: MenuItem, userRole: string, hasPermission: (perm: string) => boolean): boolean {
  const { permission } = item;
  if (!permission) return true;
  if (permission.adminOnly) return userRole === 'admin';
  if (permission.requiredRole) return hasRoleLevel(userRole, permission.requiredRole);
  if (permission.requiredPermission) return hasPermission(permission.requiredPermission);
  return true;
}

// ────────────────────────────────────────────────────────────
// 单个菜单项
// ────────────────────────────────────────────────────────────
function SidebarItem({
  item,
  collapsed,
}: {
  item: MenuItem;
  collapsed: boolean;
}) {
  const location = useLocation();
  const isActive = item.path
    ? location.pathname === item.path ||
      location.pathname.startsWith(item.path + '/')
    : false;

  if (item.hidden) return null;

  const content = (
    <div
      className={`
        flex items-center gap-2.5 px-3 py-2.5 rounded-lg mb-0.5 transition-all duration-150 cursor-pointer
        ${isActive
          ? 'bg-blue-50 text-blue-700 font-semibold'
          : item.disabled
            ? 'text-slate-300 cursor-not-allowed'
            : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
        }
      `}
      title={collapsed && !item.disabled ? item.label : undefined}
    >
      {item.icon && (
        <i className={`${item.icon} text-base shrink-0`} />
      )}
      {!collapsed && (
        <span className="text-[13px] font-medium truncate flex-1">
          {item.label}
        </span>
      )}
      {!collapsed && item.badge != null && item.badge > 0 && (
        <span className="ml-auto text-[10px] bg-red-500 text-white rounded-full px-1.5 py-0.5 font-bold">
          {item.badge > 99 ? '99+' : item.badge}
        </span>
      )}
    </div>
  );

  if (item.disabled) {
    return (
      <div
        className="relative group"
        title={collapsed ? '功能开发中，敬请期待' : undefined}
        data-tooltip={!collapsed ? '功能开发中，敬请期待' : undefined}
      >
        {content}
        {/* 非折叠时用 tooltip */}
        {!collapsed && (
          <div className="absolute left-full top-1/2 -translate-y-1/2 ml-2 px-2 py-1 bg-slate-800 text-white text-[11px] rounded whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none z-50 transition-opacity">
            功能开发中，敬请期待
          </div>
        )}
      </div>
    );
  }

  if (!item.path) return <div>{content}</div>;

  return (
    <Link to={item.path} className="block">
      {content}
    </Link>
  );
}

// ────────────────────────────────────────────────────────────
// 单个域分组
// ────────────────────────────────────────────────────────────
function DomainGroup({
  domain,
  expanded,
  onToggle,
  collapsed,
  userRole,
  hasPermission,
}: {
  domain: MenuDomain;
  expanded: boolean;
  onToggle: () => void;
  collapsed: boolean;
  userRole: string;
  hasPermission: (perm: string) => boolean;
}) {
  const location = useLocation();

  // 域下是否有可见菜单项
  const visibleItems = domain.items.filter((item) => isItemVisible(item, userRole, hasPermission));
  if (visibleItems.length === 0) return null;

  // 当前路径是否激活本域
  const isAnyActive = visibleItems.some(
    (item) =>
      item.path &&
      (location.pathname === item.path ||
        location.pathname.startsWith(item.path + '/'))
  );

  if (collapsed) {
    return (
      <div className="relative group" title={`${domain.label}：${domain.description}`}>
        <button
          onClick={onToggle}
          className={`
            w-full flex flex-col items-center justify-center py-3 rounded-lg mb-1 transition-colors
            ${isAnyActive ? 'bg-blue-50 text-blue-700' : 'text-slate-500 hover:bg-slate-50'}
          `}
        >
          <i className={`${domain.icon} text-lg`} />
          <span className="text-[10px] mt-1 leading-tight text-center px-1">
            {domain.label}
          </span>
        </button>
        {/* 折叠态 hover tooltip */}
        <div className="absolute left-full top-0 ml-2 px-3 py-2 bg-slate-800 text-white text-[12px] rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none z-50 transition-opacity whitespace-nowrap">
          <div className="font-semibold">{domain.label}</div>
          <div className="text-slate-300 text-[11px]">{domain.description}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="mb-4">
      {/* 域标题 */}
      <button
        onClick={onToggle}
        className={`
          w-full flex items-center gap-2 px-3 py-2 rounded-lg mb-1 transition-colors
          ${isAnyActive ? 'text-blue-700' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'}
        `}
      >
        <i className={`${domain.icon} text-base`} />
        <span className="text-[12px] font-semibold flex-1 text-left truncate">
          {domain.label}
        </span>
        <i
          className={`ri-arrow-down-s-line text-base transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </button>

      {/* 菜单项列表 */}
      {expanded && (
        <div className="pl-1">
          {visibleItems.map((item) => (
            <SidebarItem key={item.key} item={item} collapsed={false} />
          ))}
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// AppSidebar 主体
// ────────────────────────────────────────────────────────────
interface AppSidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function AppSidebar({ collapsed, onToggleCollapse }: AppSidebarProps) {
  const { user, hasPermission } = useAuth();
  const userRole = user?.role ?? 'user';
  const location = useLocation();

  const [domainOpenMap, setDomainOpenMap] = useState<Record<string, boolean>>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY_DOMAIN_OPEN);
      return stored ? JSON.parse(stored) : {};
    } catch {
      return {};
    }
  });

  // 持久化域展开状态
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY_DOMAIN_OPEN, JSON.stringify(domainOpenMap));
    } catch (_err) {
      // ignore localStorage write failures
    }
  }, [domainOpenMap]);

  const toggleDomain = (key: string) => {
    setDomainOpenMap((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // 路由变化时，自动展开当前所属域
  useEffect(() => {
    for (const domain of menuConfig) {
      const hasActive = domain.items.some(
        (item) =>
          item.path &&
          (location.pathname === item.path ||
            location.pathname.startsWith(item.path + '/'))
      );
      if (hasActive) {
        setDomainOpenMap((prev) => (
          prev[domain.key] ? prev : { ...prev, [domain.key]: true }
        ));
      }
    }
  }, [location.pathname]);

  const width = collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH;

  return (
    <aside
      className="bg-white border-r border-slate-200 text-slate-700 flex flex-col shrink-0 transition-all duration-200"
      style={{ width, minWidth: width }}
    >
      {/* 折叠/展开按钮 */}
      <div className="flex items-center justify-end px-2 pt-4 pb-2">
        <button
          onClick={onToggleCollapse}
          className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-50 hover:text-slate-600 transition-colors"
          title={collapsed ? '展开侧边栏' : '折叠侧边栏'}
        >
          <i className={`ri-sidebar-fold-line text-lg ${collapsed ? 'rotate-180' : ''}`} />
        </button>
      </div>

      {/* 域列表 */}
      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {/* 首页直达 */}
        <Link
          to="/"
          className={`
            flex items-center gap-2.5 px-3 py-2.5 rounded-lg mb-3 transition-all duration-150
            ${location.pathname === '/'
              ? 'bg-blue-50 text-blue-700 font-semibold'
              : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
            }
          `}
          title={collapsed ? '首页' : undefined}
        >
          <i className="ri-home-4-line text-base shrink-0" />
          {!collapsed && (
            <span className="text-[13px] font-medium truncate">首页</span>
          )}
        </Link>

        {menuConfig.map((domain) => {
          const domainPermission = domain.permission;
          if (domainPermission?.requiredRole && !hasRoleLevel(userRole, domainPermission.requiredRole)) {
            return null;
          }

          const resolvedOpen = domainOpenMap[domain.key] ?? domain.defaultOpen ?? false;

          return (
            <DomainGroup
              key={domain.key}
              domain={domain}
              expanded={resolvedOpen}
              onToggle={() => toggleDomain(domain.key)}
              collapsed={collapsed}
              userRole={userRole}
              hasPermission={hasPermission}
            />
          );
        })}
      </nav>

      {/* 底部：返回首页 */}
      <div className="px-2 py-3 border-t border-slate-100">
        <Link
          to="/"
          className={`
            flex items-center gap-2 px-3 py-2 rounded-lg transition-colors
            ${location.pathname === '/' ? 'text-blue-600 bg-blue-50' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'}
          `}
          title={collapsed ? '返回首页' : undefined}
        >
          <i className="ri-arrow-left-line text-base" />
          {!collapsed && <span className="text-[13px] font-medium">返回首页</span>}
        </Link>
      </div>
    </aside>
  );
}
