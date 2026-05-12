/**
 * 7 域菜单配置（Spec 18 v0.3 §5.2）
 *
 * 域顺序（固定）：home → query → assets → governance → agents → config → admin
 * 配置域（config）在管理域（admin）左侧
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
// 完整菜单配置（Spec 18 v0.3 §2.0，7域）
// 顺序：assets（资产）、governance（治理）、agents（智能体）、config（配置）、admin（管理）
// 注：首页入口由 AppSidebar 硬编码直达链接提供，不在此处重复
// ============================================================
export const menuConfig: MenuDomain[] = [

  // 问数域已移除（当前阶段所有问数走首页 Data Agent）

  // ──────────────────────────────────────────────────
  // 域 2：资产 /assets
  // ──────────────────────────────────────────────────
  {
    key: 'assets',
    label: '资产',
    icon: 'ri-stack-line',
    description: 'BI 资产浏览、数据源连接与 Tableau 资产管理',
    defaultOpen: false,
    permission: { requiredRole: 'analyst' },
    items: [
      {
        key: 'dw-assets',
        label: '数仓资产',
        icon: 'ri-database-2-line',
        path: '/assets/dw',
        permission: { requiredRole: 'analyst' },
      },
      {
        key: 'tableau-assets',
        label: 'Tableau 资产',
        icon: 'ri-bar-chart-box-line',
        path: '/assets/tableau',
      },
      {
        key: 'knowledge',
        label: '知识库',
        icon: 'ri-book-open-line',
        path: '/assets/knowledge',
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 3：治理 /governance（Spec 18 v0.4）
  // ──────────────────────────────────────────────────
  {
    key: 'governance',
    label: '治理',
    icon: 'ri-shield-star-line',
    description: '数据质量、语义治理、合规管理与 DQC',
    defaultOpen: true,
    permission: { requiredRole: 'analyst' },
    items: [
      {
        key: 'dw-audit',
        label: '数仓巡检',
        icon: 'ri-heart-pulse-line',
        path: '/governance/dw-audit',
      },
      {
        key: 'tableau-audit',
        label: 'Tableau 巡检',
        icon: 'ri-pulse-line',
        path: '/governance/tableau-audit',
      },
      {
        key: 'dqc',
        label: '数据质量监控',
        icon: 'ri-dashboard-line',
        path: '/governance/dqc',
      },
      {
        key: 'semantic',
        label: '语义治理',
        icon: 'ri-database-2-line',
        path: '/governance/semantic',
      },
      {
        key: 'metrics',
        label: '指标治理',
        icon: 'ri-hammer-line',
        path: '/governance/metrics',
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 4：智能体 /agents（Spec 28、29、30）
  // ──────────────────────────────────────────────────
  {
    key: 'agents',
    label: '智能体',
    icon: 'ri-robot-line',
    description: 'Data Agent、SQL Agent、Metrics Agent 与 Agent 监控',
    defaultOpen: false,
    items: [
      {
        key: 'data-agent',
        label: 'Data Agent',
        icon: 'ri-bar-chart-2-line',
        path: '/agents/data',
      },
      {
        key: 'sql-agent',
        label: 'SQL Agent',
        icon: 'ri-file-code-line',
        path: '/agents/sql',
      },
      {
        key: 'metrics-agent',
        label: 'Metrics Agent',
        icon: 'ri-line-chart-line',
        path: '/agents/metrics',
      },
      {
        key: 'help-agent',
        label: 'Help Agent',
        icon: 'ri-question-answer-line',
        path: '/agents/help',
      },
      {
        key: 'agent-monitor',
        label: 'Agent 监控',
        icon: 'ri-eye-line',
        path: '/agents/agent-monitor',
      },
      {
        key: 'skills',
        label: '技能中心',
        icon: 'ri-puzzle-2-line',
        path: '/agents/skills',
      },
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 5：配置 /config（原平台 + 实验室内容合并）
  // ──────────────────────────────────────────────────
  {
    key: 'config',
    label: '配置',
    icon: 'ri-server-line',
    description: '数据连接、服务配置、任务调度',
    defaultOpen: false,
    permission: { requiredRole: 'data_admin' },
    items: [
      {
        key: 'data-connections',
        label: '数据连接',
        icon: 'ri-server-line',
        path: '/system/data-connections',
        permission: { requiredRole: 'data_admin' },
      },
      {
        key: 'service-configs',
        label: '服务配置',
        icon: 'ri-settings-3-line',
        path: '/system/service-configs',
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
    ],
  },

  // ──────────────────────────────────────────────────
  // 域 6：管理 /admin（原系统/设置）
  // ──────────────────────────────────────────────────
  {
    key: 'admin',
    label: '管理',
    icon: 'ri-settings-2-line',
    description: '用户管理、权限配置、操作日志、Token 统计',
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
        key: 'token-stats',
        label: 'Token 统计',
        icon: 'ri-coin-line',
        path: '/system/usage-stats/tokens',
      },
      {
        key: 'platform-settings',
        label: '平台设置',
        icon: 'ri-image-line',
        path: '/system/platform-settings',
      },
      // ── 账户设置 ──
      {
        key: 'notifications',
        label: '消息通知',
        icon: 'ri-notification-3-line',
        path: '/notifications',
      },
      {
        key: 'account-profile',
        label: '个人中心',
        icon: 'ri-user-3-line',
        path: '/account/profile',
      },
    ],
  },
];

// ============================================================
// localStorage keys（Spec 18 §5.3）
// ============================================================
export const STORAGE_KEY_SIDEBAR_COLLAPSED = 'mulan-sidebar-collapsed';
export const STORAGE_KEY_DOMAIN_OPEN = 'mulan-sidebar-domains';
