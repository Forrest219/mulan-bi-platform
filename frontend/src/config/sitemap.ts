import { menuConfig, hasRoleLevel, type MenuPermission } from './menu';
import EXTRA_DESCRIPTIONS from './sitemap-descriptions.json';

export interface SitemapEntry {
  key: string;
  label: string;
  group: string;
  path: string;
  icon: string;
  keywords: string[];
  description?: string;
}

// Extra search keywords per menu item key
const EXTRA_KEYWORDS: Record<string, string[]> = {
  'tableau-assets':      ['资产', '看板', '工作簿', 'workbook', 'dashboard', '数据源'],
  'tableau-connections': ['连接', 'mcp', 'tableau', '服务器', 'server'],
  'sync-logs':           ['同步', '日志', 'sync'],
  'dw-audit':            ['巡检', '健康', '数仓', '扫描', '检查'],
  'tableau-audit':       ['tableau', '审计', '质量', '巡检'],
  'dqc':                 ['质量', '监控', '规则', '告警', '检查'],
  'semantic':            ['语义', '字段', '标注', '治理', '元数据'],
  'metrics':             ['指标', '度量', '派生', '原子', '比率'],
  'knowledge':           ['知识', '文档', '术语', '知识库'],
  'data-agent':          ['分析', '问数', '对话', 'agent', 'ai'],
  'data-agent-history':  ['历史', '执行记录', 'agent'],
  'sql-agent':           ['sql', '查询', '数据库', 'agent'],
  'metrics-agent':       ['指标', '计算', '分析', 'agent'],
  'agent-monitor':       ['监控', '日志', 'agent', '执行'],
  'llm':                 ['大模型', 'llm', 'openai', 'api key', '模型', 'claude', 'gpt'],
  'mcp-configs':         ['mcp', '服务器', 'tableau', '连接配置', '插件'],
  'datasources':         ['数据库', 'mysql', 'postgresql', '连接', 'db', 'starrocks'],
  'mcp-debugger':        ['调试', 'debug', 'mcp', '工具', '测试'],
  'tasks':               ['任务', '调度', '定时'],
  'query-alerts':        ['查询', '告警', '日志', '记录', '问数日志'],
  'users':               ['用户', '账号', '管理', '成员'],
  'groups':              ['用户组', '团队', '权限', '角色'],
  'permissions':         ['权限', '配置', 'rbac', '角色', '授权'],
  'shared-permissions':  ['共享', '权限', '数据源', '分享'],
  'activity':            ['操作日志', '审计', '记录', '活动', '行为'],
  'platform-settings':   ['平台', 'logo', '名称', '副标题', '设置', '配置', 'favicon'],
  'account-security':    ['安全', '密码策略', '账户', '防护'],
};

interface VirtualEntry extends SitemapEntry {
  permission?: MenuPermission;
}

// Sub-page features not directly represented in menuConfig
const VIRTUAL_ENTRIES: VirtualEntry[] = [
  {
    key: 'platform-smtp',
    label: '邮件通知',
    group: '平台设置',
    path: '/system/platform-settings?tab=email',
    icon: 'ri-mail-settings-line',
    keywords: ['邮件', 'smtp', 'email', '邮箱', '通知', '发件人', '邮件服务器'],
    permission: { adminOnly: true },
  },
  {
    key: 'account-password',
    label: '修改密码',
    group: '账户',
    path: '/account/password',
    icon: 'ri-lock-password-line',
    keywords: ['密码', '改密', '修改密码', '安全'],
  },
  {
    key: 'account-profile',
    label: '个人中心',
    group: '账户',
    path: '/account/profile',
    icon: 'ri-user-3-line',
    keywords: ['个人', '资料', '头像', '账户', '我的'],
  },
  {
    key: 'home',
    label: '首页',
    group: '',
    path: '/',
    icon: 'ri-home-4-line',
    keywords: ['首页', '主页', '问数', '对话'],
  },
];

function isVisible(
  permission: MenuPermission | undefined,
  role: string,
  hasPermission: (p: string) => boolean,
): boolean {
  if (!permission) return true;
  if (permission.adminOnly) return role === 'admin';
  if (permission.requiredRole) return hasRoleLevel(role, permission.requiredRole);
  if (permission.requiredPermission) return hasPermission(permission.requiredPermission);
  return true;
}

export function buildSearchEntries(
  role: string,
  hasPermission: (p: string) => boolean,
): SitemapEntry[] {
  const entries: SitemapEntry[] = [];

  for (const domain of menuConfig) {
    if (!isVisible(domain.permission, role, hasPermission)) continue;

    for (const item of domain.items) {
      if (item.hidden || item.disabled || !item.path) continue;
      // Item permission takes precedence; fall back to domain permission
      const effectivePermission = item.permission ?? (domain.permission?.requiredRole ? domain.permission : undefined);
      if (!isVisible(effectivePermission, role, hasPermission)) continue;

      entries.push({
        key: item.key,
        label: item.label,
        group: domain.label,
        path: item.path,
        icon: item.icon ?? 'ri-pages-line',
        keywords: EXTRA_KEYWORDS[item.key] ?? [],
        description: EXTRA_DESCRIPTIONS[item.key],
      });
    }
  }

  for (const { permission, ...entry } of VIRTUAL_ENTRIES) {
    if (isVisible(permission, role, hasPermission)) {
      entries.push({
        ...entry,
        description: EXTRA_DESCRIPTIONS[entry.key] ?? entry.description,
      });
    }
  }

  return entries;
}

export function searchEntries(entries: SitemapEntry[], query: string): SitemapEntry[] {
  if (!query.trim()) return [];
  const terms = query.toLowerCase().trim().split(/\s+/);
  return entries
    .filter(entry => {
      const haystack = [entry.label, entry.group, ...entry.keywords].join(' ').toLowerCase();
      return terms.every(term => haystack.includes(term));
    })
    .slice(0, 7);
}
