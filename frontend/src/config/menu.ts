/**
 * 5 域菜单配置（Spec 18 §5.2）
 *
 * P0 约束：
 * - ddl-generator / nl-query / publish-logs 必须配置 requiredRole + disabled
 * - 绝对禁止对 src/api/ 目录下的后端 API 路径做替换
 */

// ============================================================
// 角色层级（用于 requiredRole 比较）
// ============================================================
export const ROLE_LEVEL: Record<string, number> = {
  admin: 4,
  data_admin: 3,
  analyst: 2,
  user: 1,
};

/** 判断用户角色是否 >= 所需角色 */
export function hasRoleLevel(userRole: string, requiredRole: string): boolean {
  return (ROLE_LEVEL[userRole] ?? 0) >= (ROLE_LEVEL[requiredRole] ?? 0);
}

// ============================================================
// 权限控制接口（Spec 18 §3.3）
// ============================================================
export interface MenuPermission {
  requiredRole?: 'admin' | 'data_admin' | 'analyst' | 'user';
  requiredPermission?: string;
  adminOnly?: boolean;
}

// ============================================================
// 菜单项（Spec 18 §5.2 MenuItem）
// ============================================================
export interface MenuItem {
  key: string;
  label: string;
  icon?: string;
  path?: string;
  permission?: MenuPermission;
  children?: MenuItem[];
  /** 是否在菜单中隐藏（详情页等动态路由） */
  hidden?: boolean;
  /** 是否置灰禁用（待开发功能，hover 显示 tooltip 提示"功能开发中，敬请期待"） */
  disabled?: boolean;
  badge?: number;
}

// ============================================================
// 域配置（Spec 18 §5.2 MenuDomain）
// ============================================================
export interface MenuDomain {
  key: string;
  label: string;
  icon: string;
  description: string;
  permission?: MenuPermission;
  defaultOpen?: boolean;
  items: MenuItem[];
}

// ============================================================
// 完整菜单配置（Spec 18 §5.2 menuConfig）
// ============================================================
export const menuConfig: MenuDomain[] = [
  // ──────────────────────────────────────────────────
  // 域 0：运维工作台 /（登录即可访问）
  // ──────────────────────────────────────────────────
  {
    key: 'ops',
    label: '运维工作台',
    icon: 'ri-dashboard-3-line',
    description: '资产浏览与问数一体化工作台',
    defaultOpen: false,
    items: [
      {
        key: 'ops-home',
        label: '工作台',
        icon: 'ri-dashboard-3-line',
        path: '/',
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 1：数据开发 /dev
  // ──────────────────────────────────────────────────
  {
    key: 'dev',
    label: '数据开发',
    icon: 'ri-terminal-box-line',
    description: '数据库开发工具与规范管理',
    defaultOpen: false,
    items: [
      {
        key: 'ddl-validator',
        label: 'DDL 检查',
        icon: 'ri-code-s-slash-line',
        path: '/dev/ddl-validator',
      },
      // ⚠️ 待开发：analyst+ 可访问，disabled 置灰
      {
        key: 'ddl-generator',
        label: 'DDL 生成器',
        icon: 'ri-file-code-line',
        path: '/dev/ddl-generator',
        permission: { requiredRole: 'analyst' },
        disabled: true,
      },
      {
        key: 'rule-config',
        label: '规则配置',
        icon: 'ri-settings-3-line',
        path: '/dev/rule-config',
        permission: { requiredRole: 'data_admin' },
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 2：数据治理 /governance
  // ──────────────────────────────────────────────────
  {
    key: 'governance',
    label: '数据治理',
    icon: 'ri-shield-star-line',
    description: '数据质量、语义治理与合规管理',
    defaultOpen: true,
    permission: { requiredRole: 'analyst' },
    items: [
      {
        key: 'health',
        label: '健康扫描',
        icon: 'ri-heart-pulse-line',
        path: '/governance/health',
      },
      {
        key: 'quality',
        label: '质量监控',
        icon: 'ri-shield-check-line',
        path: '/governance/quality',
      },
      {
        key: 'semantic-ds',
        label: '语义 - 数据源',
        icon: 'ri-database-2-line',
        path: '/governance/semantic/datasources',
      },
      {
        key: 'semantic-fields',
        label: '语义 - 字段',
        icon: 'ri-list-settings-line',
        path: '/governance/semantic/fields',
      },
      // ⚠️ 待开发：权限跟随域（analyst+）
      {
        key: 'publish-logs',
        label: '发布日志',
        icon: 'ri-file-list-3-line',
        path: '/governance/semantic/publish-logs',
        disabled: true,
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 3：数据资产 /assets
  // ──────────────────────────────────────────────────
  {
    key: 'assets',
    label: '数据资产',
    icon: 'ri-stack-line',
    description: 'BI 资产浏览与数据源连接管理',
    defaultOpen: false,
    permission: { requiredRole: 'analyst' },
    items: [
      {
        key: 'tableau-assets',
        label: 'Tableau 资产',
        icon: 'ri-bar-chart-box-line',
        path: '/assets/tableau',
      },
      {
        key: 'tableau-health',
        label: 'Tableau 健康',
        icon: 'ri-pulse-line',
        path: '/assets/tableau-health',
      },
      {
        key: 'datasources',
        label: '数据源管理',
        icon: 'ri-database-2-line',
        path: '/assets/datasources',
        permission: { requiredRole: 'data_admin' },
      },
      {
        key: 'tableau-conn',
        label: 'Tableau 连接',
        icon: 'ri-links-line',
        path: '/assets/tableau-connections',
        permission: { requiredRole: 'data_admin' },
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 4：智能分析 /analytics
  // ──────────────────────────────────────────────────
  {
    key: 'analytics',
    label: '智能分析',
    icon: 'ri-brain-line',
    description: 'AI 驱动的数据分析与知识管理',
    defaultOpen: false,
    items: [
      // ⚠️ 待开发：analyst+ 可访问，disabled 置灰
      {
        key: 'nl-query',
        label: '自然语言查询',
        icon: 'ri-chat-search-line',
        path: '/analytics/nl-query',
        permission: { requiredRole: 'analyst' },
        disabled: true,
      },
      {
        key: 'knowledge',
        label: '知识库',
        icon: 'ri-book-open-line',
        path: '/analytics/knowledge',
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 5：系统管理 /system
  // ──────────────────────────────────────────────────
  {
    key: 'system',
    label: '系统管理',
    icon: 'ri-settings-2-line',
    description: '平台配置、用户管理与系统监控',
    defaultOpen: false,
    permission: { requiredRole: 'admin' },
    items: [
      {
        key: 'users',
        label: '用户管理',
        icon: 'ri-user-settings-line',
        path: '/system/users',
      },
      {
        key: 'groups',
        label: '用户组',
        icon: 'ri-team-line',
        path: '/system/groups',
      },
      {
        key: 'permissions',
        label: '权限配置',
        icon: 'ri-shield-keyhole-line',
        path: '/system/permissions',
      },
      {
        key: 'llm',
        label: 'LLM 配置',
        icon: 'ri-robot-line',
        path: '/system/llm-configs',
      },
      {
        key: 'mcp-configs',
        label: 'MCP 配置',
        icon: 'ri-plug-line',
        path: '/system/mcp-configs',
      },
      {
        key: 'mcp-debugger',
        label: 'MCP 调试器',
        icon: 'ri-bug-line',
        path: '/system/mcp-debugger',
      },
      {
        key: 'tasks',
        label: '任务管理',
        icon: 'ri-task-line',
        path: '/system/tasks',
      },
      {
        key: 'activity',
        label: '操作日志',
        icon: 'ri-history-line',
        path: '/system/activity',
      },
    ],
  },
];

// ============================================================
// localStorage keys（Spec 18 §5.3）
// ============================================================
export const STORAGE_KEY_SIDEBAR_COLLAPSED = 'mulan-sidebar-collapsed';
export const STORAGE_KEY_DOMAIN_OPEN = 'mulan-sidebar-domains';
