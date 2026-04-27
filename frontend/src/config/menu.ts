/**
 * 5 域菜单配置（Spec 18 §5.2）
 *
 * P0 约束：
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
  // 运维工作台（Spec 20，独立入口）
  // ──────────────────────────────────────────────────
  {
    key: 'ops',
    label: '运维',
    icon: 'ri-dashboard-3-line',
    description: '运维工作台：问数、资产、健康一站式',
    defaultOpen: true,
    items: [
      {
        key: 'workbench',
        label: '运维工作台',
        icon: 'ri-dashboard-3-line',
        path: '/ops/workbench',
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 1：资产 /assets
  // ──────────────────────────────────────────────────
  {
    key: 'assets',
    label: '资产',
    icon: 'ri-stack-line',
    description: 'BI 资产浏览',
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
        key: 'connections',
        label: '连接总览',
        icon: 'ri-links-line',
        path: '/assets/connections',
      },
      {
        key: 'datasources',
        label: '数据源管理',
        icon: 'ri-database-2-line',
        path: '/assets/datasources',
        permission: { requiredRole: 'data_admin' },
      },
      {
        key: 'tableau-connections',
        label: 'Tableau 连接',
        icon: 'ri-plug-line',
        path: '/assets/tableau-connections',
        permission: { requiredPermission: 'tableau' },
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 2：治理 /governance
  // ──────────────────────────────────────────────────
  {
    key: 'governance',
    label: '治理',
    icon: 'ri-shield-star-line',
    description: '数据质量、语义治理与合规管理',
    defaultOpen: true,
    permission: { requiredRole: 'analyst' },
    items: [
      {
        key: 'health-center',
        label: '健康中心',
        icon: 'ri-heart-pulse-line',
        path: '/governance/health-center',
      },
      {
        key: 'semantic',
        label: '语义治理',
        icon: 'ri-database-2-line',
        path: '/governance/semantic/datasources',
      },
      {
        key: 'metrics',
        label: '指标管理',
        icon: 'ri-bar-chart-grouped-line',
        path: '/governance/metrics',
      },
      {
        key: 'publish-logs',
        label: '发布日志',
        icon: 'ri-file-list-3-line',
        path: '/governance/semantic/publish-logs',
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 3：平台（基础设施、任务与监控）
  // ──────────────────────────────────────────────────
  {
    key: 'platform',
    label: '平台',
    icon: 'ri-server-line',
    description: '数据源连接、LLM/MCP 配置、任务调度与告警',
    defaultOpen: false,
    permission: { requiredRole: 'data_admin' },
    items: [
      {
        key: 'connections',
        label: '数据源与连接',
        icon: 'ri-links-line',
        path: '/assets/connections',
      },
      {
        key: 'tableau-connections',
        label: 'Tableau 连接',
        icon: 'ri-plug-line',
        path: '/assets/tableau-connections',
        permission: { requiredPermission: 'tableau' },
      },
      {
        key: 'llm',
        label: 'LLM 配置',
        icon: 'ri-robot-line',
        path: '/system/llm-configs',
        permission: { adminOnly: true },
      },
      {
        key: 'mcp-configs',
        label: 'MCP 配置',
        icon: 'ri-plug-line',
        path: '/system/mcp-configs',
        permission: { adminOnly: true },
      },
      {
        key: 'mcp-debugger',
        label: 'MCP 调试器',
        icon: 'ri-bug-line',
        path: '/system/mcp-debugger',
        permission: { adminOnly: true },
      },
      {
        key: 'tasks',
        label: '任务管理',
        icon: 'ri-task-line',
        path: '/system/tasks',
        permission: { adminOnly: true },
      },
      {
        key: 'query-alerts',
        label: '问数告警',
        icon: 'ri-alarm-warning-line',
        path: '/system/query-alerts',
        permission: { adminOnly: true },
      },
      {
        key: 'agent-monitor',
        label: 'Agent 监控',
        icon: 'ri-robot-line',
        path: '/system/agent-monitor',
        permission: { adminOnly: true },
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 4：实验室（数据开发 + 智能分析）
  // ──────────────────────────────────────────────────
  {
    key: 'lab',
    label: '实验室',
    icon: 'ri-flask-line',
    description: '数据库开发工具、规范管理与 AI 分析',
    defaultOpen: false,
    items: [
      {
        key: 'ddl-validator',
        label: 'DDL 检查',
        icon: 'ri-code-s-slash-line',
        path: '/dev/ddl-validator',
      },
      {
        key: 'ddl-generator',
        label: 'DDL 生成器',
        icon: 'ri-file-code-line',
        path: '/empty/ddl-generator',
        permission: { requiredRole: 'analyst' },
        hidden: true,
      },
      {
        key: 'rule-config',
        label: '规则配置',
        icon: 'ri-settings-3-line',
        path: '/dev/rule-config',
        permission: { requiredRole: 'data_admin' },
      },
      {
        key: 'nl-query',
        label: '自然语言查询',
        icon: 'ri-chat-search-line',
        path: '/empty/nl-query',
        permission: { requiredRole: 'analyst' },
        hidden: true,
      },
      {
        key: 'knowledge',
        label: '知识库',
        icon: 'ri-book-open-line',
        path: '/empty/knowledge-base',
        hidden: true,
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 5：设置（IAM + 审计）
  // ──────────────────────────────────────────────────
  {
    key: 'system',
    label: '设置',
    icon: 'ri-settings-2-line',
    description: '用户管理、权限配置与操作审计',
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
        key: 'activity',
        label: '操作日志',
        icon: 'ri-history-line',
        path: '/system/activity',
      },
      {
        key: 'platform-settings',
        label: 'Logo',
        icon: 'ri-image-line',
        path: '/system/platform-settings',
        permission: { adminOnly: true },
      },
    ],
  },
];

// ============================================================
// localStorage keys（Spec 18 §5.3）
// ============================================================
export const STORAGE_KEY_SIDEBAR_COLLAPSED = 'mulan-sidebar-collapsed';
export const STORAGE_KEY_DOMAIN_OPEN = 'mulan-sidebar-domains';
