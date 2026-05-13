import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../../context/AuthContext';
import {
  listSkills, patchSkill,
  type AgentSkill, type SkillListParams,
} from '../../../api/skills';

// ── 工具函数 ──────────────────────────────────────────────────────────────────

function formatTimeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  return `${days}天前`;
}

const CATEGORY_LABELS: Record<string, string> = {
  query: '查询',
  analysis: '分析',
  visualization: '可视化',
  reporting: '报告',
  general: '通用',
};

const CATEGORY_COLORS: Record<string, string> = {
  query: 'bg-blue-50 text-blue-700 border-blue-200',
  analysis: 'bg-purple-50 text-purple-700 border-purple-200',
  visualization: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  reporting: 'bg-amber-50 text-amber-700 border-amber-200',
  general: 'bg-slate-100 text-slate-600 border-slate-200',
};

const CATEGORIES = [
  { key: '', label: '全部' },
  { key: 'query', label: '查询' },
  { key: 'analysis', label: '分析' },
  { key: 'visualization', label: '可视化' },
  { key: 'reporting', label: '报告' },
];

const CONFIG_SYNC_MESSAGE = '配置已保存，最多约 10 秒后在所有服务实例生效';

// ── 主页面 ─────────────────────────────────────────────────────────────────────

export default function SkillsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [skills, setSkills] = useState<AgentSkill[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const [categoryFilter, setCategoryFilter] = useState('');
  const [enabledFilter, setEnabledFilter] = useState<'' | 'true' | 'false'>('');
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const loadSkills = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params: SkillListParams = { page, page_size: pageSize };
      if (categoryFilter) params.category = categoryFilter;
      if (enabledFilter !== '') params.is_enabled = enabledFilter === 'true';
      if (search) params.q = search;
      const res = await listSkills(params);
      setSkills(res.items);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page, categoryFilter, enabledFilter, search]);

  useEffect(() => { loadSkills(); }, [loadSkills]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSearch(searchInput);
    setPage(1);
  };

  const handleCategoryChange = (key: string) => {
    setCategoryFilter(key);
    setPage(1);
  };

  const showSuccess = (msg: string) => {
    setSuccessMsg(msg);
    setTimeout(() => setSuccessMsg(''), 3000);
  };

  const handleToggleEnabled = async (skill: AgentSkill) => {
    if (!isAdmin || togglingId) return;
    setTogglingId(skill.id);
    setError('');
    try {
      const updated = await patchSkill(skill.id, { is_enabled: !skill.is_enabled });
      setSkills(prev => prev.map(item => (item.id === skill.id ? { ...item, ...updated } : item)));
      showSuccess(CONFIG_SYNC_MESSAGE);
    } catch (e) {
      setError(e instanceof Error ? e.message : '更新失败');
    } finally {
      setTogglingId(null);
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页面头部 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-puzzle-2-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">技能中心</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">管理 Agent 可调用的技能定义与版本</p>
          </div>
          {isAdmin && (
            <button
              onClick={() => navigate('/agents/skills/create')}
              className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 text-white text-[13px] rounded-lg hover:bg-blue-700"
            >
              <i className="ri-add-line" />从已注册工具添加
            </button>
          )}
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="max-w-6xl mx-auto">
          {error && (
            <div className="mb-4 px-4 py-3 bg-red-50 text-red-700 border border-red-200 rounded-lg text-[13px] flex items-center justify-between">
              <span>{error}</span>
              <button onClick={() => setError('')} className="text-red-400 hover:text-red-600">
                <i className="ri-close-line" />
              </button>
            </div>
          )}
          {successMsg && (
            <div className="mb-4 px-4 py-3 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-lg text-[13px] flex items-center justify-between">
              <span>{successMsg}</span>
              <button onClick={() => setSuccessMsg('')} className="text-emerald-400 hover:text-emerald-600">
                <i className="ri-close-line" />
              </button>
            </div>
          )}

          {/* 筛选栏 */}
          <div className="bg-white border border-slate-200 rounded-xl px-5 py-3 mb-4 flex items-center gap-4 flex-wrap">
            {/* 分类 Tab */}
            <div className="flex items-center gap-1">
              {CATEGORIES.map(c => (
                <button
                  key={c.key}
                  onClick={() => handleCategoryChange(c.key)}
                  className={`px-3 py-1.5 text-[12px] rounded-lg transition-colors ${
                    categoryFilter === c.key
                      ? 'bg-blue-600 text-white'
                      : 'text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  {c.label}
                </button>
              ))}
            </div>

            <div className="flex-1" />

            {/* 搜索框 */}
            <form onSubmit={handleSearchSubmit} className="relative">
              <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm" />
              <input
                value={searchInput}
                onChange={e => setSearchInput(e.target.value)}
                placeholder="技能名称 / 标识"
                className="pl-9 pr-3 py-1.5 text-[12px] border border-slate-200 rounded-lg w-44 focus:outline-none focus:border-blue-400"
              />
            </form>

            {/* 启用状态下拉 */}
            <select
              value={enabledFilter}
              onChange={e => { setEnabledFilter(e.target.value as '' | 'true' | 'false'); setPage(1); }}
              className="px-3 py-1.5 text-[12px] border border-slate-200 rounded-lg bg-white focus:outline-none focus:border-blue-400"
            >
              <option value="">全部状态</option>
              <option value="true">已启用</option>
              <option value="false">已禁用</option>
            </select>
          </div>

          {/* 列表表格 */}
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-5 py-3">技能名称</th>
                  <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 w-20">分类</th>
                  <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 w-20">活跃版本</th>
                  <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 w-20">状态</th>
                  <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 w-28">最近更新</th>
                  <th className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 w-36">操作</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={6} className="text-center py-12 text-[13px] text-slate-400">
                      <i className="ri-loader-4-line animate-spin mr-2" />加载中...
                    </td>
                  </tr>
                ) : skills.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="text-center py-12 text-[13px] text-slate-400">
                      <i className="ri-puzzle-2-line text-3xl text-slate-200 block mb-2" />
                      暂无技能数据
                    </td>
                  </tr>
                ) : (
                  skills.map(skill => (
                    <SkillRow
                      key={skill.id}
                      skill={skill}
                      isAdmin={isAdmin}
                      toggling={togglingId === skill.id}
                      onRowClick={() => navigate(`/agents/skills/${skill.id}`)}
                      onToggleEnabled={(e) => {
                        e.stopPropagation();
                        handleToggleEnabled(skill);
                      }}
                      onPublishClick={(e) => {
                        e.stopPropagation();
                        navigate(`/agents/skills/${skill.id}`);
                      }}
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* 分页 */}
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <span className="text-[12px] text-slate-500">共 {total} 条记录</span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1.5 text-[12px] border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <i className="ri-arrow-left-s-line" />
                </button>
                {Array.from({ length: totalPages }, (_, i) => i + 1)
                  .filter(p => Math.abs(p - page) <= 2)
                  .map(p => (
                    <button
                      key={p}
                      onClick={() => setPage(p)}
                      className={`px-3 py-1.5 text-[12px] border rounded-lg ${
                        p === page
                          ? 'bg-blue-600 text-white border-blue-600'
                          : 'border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      {p}
                    </button>
                  ))}
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="px-3 py-1.5 text-[12px] border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <i className="ri-arrow-right-s-line" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 技能行组件 ─────────────────────────────────────────────────────────────────

interface SkillRowProps {
  skill: AgentSkill;
  isAdmin: boolean;
  toggling: boolean;
  onRowClick: () => void;
  onToggleEnabled: (e: React.MouseEvent) => void;
  onPublishClick: (e: React.MouseEvent) => void;
}

function SkillRow({ skill, isAdmin, toggling, onRowClick, onToggleEnabled, onPublishClick }: SkillRowProps) {
  const categoryColor = CATEGORY_COLORS[skill.category] ?? CATEGORY_COLORS.general;
  const categoryLabel = CATEGORY_LABELS[skill.category] ?? skill.category;

  return (
    <tr
      className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer transition-colors"
      onClick={onRowClick}
    >
      {/* 技能名称 */}
      <td className="px-5 py-3">
        <div className="font-medium text-[13px] text-slate-800">{skill.name}</div>
        <div className="text-[11px] text-slate-400 font-mono mt-0.5">{skill.skill_key}</div>
      </td>
      {/* 分类 */}
      <td className="px-4 py-3">
        <span className={`inline-block text-[11px] px-2 py-0.5 rounded border font-medium ${categoryColor}`}>
          {categoryLabel}
        </span>
      </td>
      {/* 活跃版本 */}
      <td className="px-4 py-3">
        {skill.active_version ? (
          <span className="inline-block text-[11px] px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 font-medium">
            {skill.active_version.version_number}
          </span>
        ) : (
          <span className="text-[11px] text-slate-400">无</span>
        )}
      </td>
      {/* 状态 */}
      <td className="px-4 py-3">
        {isAdmin ? (
          <button
            type="button"
            onClick={onToggleEnabled}
            disabled={toggling}
            className="inline-flex items-center gap-2 disabled:opacity-50"
            aria-label={skill.is_enabled ? '禁用技能' : '启用技能'}
          >
            <span className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
              skill.is_enabled ? 'bg-blue-600' : 'bg-slate-200'
            }`}>
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                  skill.is_enabled ? 'translate-x-4' : 'translate-x-0.5'
                }`}
              />
            </span>
            <span className="text-[11px] text-slate-600">
              {toggling ? '保存中' : skill.is_enabled ? '已启用' : '已禁用'}
            </span>
          </button>
        ) : (
          <span className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full font-medium ${
            skill.is_enabled
              ? 'bg-emerald-50 text-emerald-700'
              : 'bg-slate-100 text-slate-500'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${skill.is_enabled ? 'bg-emerald-500' : 'bg-slate-400'}`} />
            {skill.is_enabled ? '已启用' : '已禁用'}
          </span>
        )}
      </td>
      {/* 最近更新 */}
      <td className="px-4 py-3 text-[12px] text-slate-500">
        {formatTimeAgo(skill.updated_at)}
      </td>
      {/* 操作 */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); onRowClick(); }}
            className="text-[12px] text-blue-600 hover:text-blue-500 px-2 py-1 rounded hover:bg-blue-50"
          >
            详情
          </button>
          {isAdmin && (
            <button
              onClick={onPublishClick}
              className="text-[12px] text-slate-600 hover:text-slate-800 px-2 py-1 rounded hover:bg-slate-100"
            >
              发布版本
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
