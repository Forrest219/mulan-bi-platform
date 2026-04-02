import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { getAsset, getAssetChildren, getAssetParent, explainAsset, getAssetHealth, TableauAsset } from '../../../api/tableau';
import type { HealthCheck } from '../../../api/tableau';
import { getAssetSummary, getLLMConfig } from '../../../api/llm';
import { ASSET_TYPE_LABELS } from '../../../config';
import { ConfirmModal } from '../../../components/ConfirmModal';

const ASSET_TYPE_ICONS: Record<string, string> = {
  workbook: 'ri-file-chart-line',
  dashboard: 'ri-dashboard-line',
  view: 'ri-bar-chart-box-line',
  datasource: 'ri-database-2-line',
};

export default function TableauAssetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [asset, setAsset] = useState<TableauAsset | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'info' | 'datasources' | 'ai' | 'children' | 'fields' | 'health'>('info');

  // AI state
  const [aiExplain, setAiExplain] = useState<string | null>(null);
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiCached, setAiCached] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState(true);
  const [fieldSemantics, setFieldSemantics] = useState<any[]>([]);

  // Health state
  const [healthData, setHealthData] = useState<{ score: number; level: string; checks: HealthCheck[] } | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);

  // Hierarchy state
  const [parentAsset, setParentAsset] = useState<TableauAsset | null>(null);
  const [children, setChildren] = useState<TableauAsset[]>([]);
  const [childrenLoading, setChildrenLoading] = useState(false);
  const [confirmModal, setConfirmModal] = useState<{ open: boolean; title: string; message: string; onConfirm: () => void } | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setParentAsset(null);
    setChildren([]);
    setAiExplain(null);
    setAiSummary(null);
    setAiError(null);

    getAsset(Number(id))
      .then(a => {
        setAsset(a);
        // Load parent for views/dashboards
        if (a.asset_type === 'view' || a.asset_type === 'dashboard') {
          getAssetParent(a.id).then(d => setParentAsset(d.parent)).catch(() => {});
        }
        // Load children for workbooks
        if (a.asset_type === 'workbook') {
          setChildrenLoading(true);
          getAssetChildren(a.id).then(d => setChildren(d.children)).catch(() => {}).finally(() => setChildrenLoading(false));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));

    getLLMConfig().then(d => {
      setLlmConfigured(!!d.config && d.config.is_active);
    }).catch(() => setLlmConfigured(false));
  }, [id]);

  // Load deep AI explain (Phase 2a)
  async function loadAIExplain(refresh = false) {
    if (!id) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const result = await explainAsset(Number(id), refresh);
      setAiExplain(result.explain);
      setAiCached(result.cached);
      setAiError(result.error || null);
      if (result.field_semantics) setFieldSemantics(result.field_semantics);
    } catch {
      // Fallback to basic summary if explain fails
      try {
        const result = await getAssetSummary(Number(id), refresh);
        setAiSummary(result.summary);
        setAiCached(result.cached);
        setAiError(result.error || null);
      } catch (e: any) {
        setAiError(e.message || '获取解读失败');
      }
    } finally {
      setAiLoading(false);
    }
  }

  function handleRefreshAI() {
    if (aiExplain || aiSummary) {
      setConfirmModal({
        open: true,
        title: '重新生成解读',
        message: '确定要重新生成 AI 深度解读吗？之前的解读将被覆盖。',
        onConfirm: () => { setConfirmModal(null); loadAIExplain(true); },
      });
    } else {
      loadAIExplain(false);
    }
  }

  const aiContent = aiExplain || aiSummary;

  // Simple markdown renderer (bold, headers, lists)
  function renderMarkdown(text: string): string {
    return text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/^### (.+)$/gm, '<h4 class="font-semibold text-slate-800 mt-4 mb-1">$1</h4>')
      .replace(/^## (.+)$/gm, '<h3 class="font-semibold text-slate-800 mt-5 mb-2 text-base">$1</h3>')
      .replace(/^# (.+)$/gm, '<h2 class="font-bold text-slate-800 mt-5 mb-2 text-lg">$1</h2>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^\- (.+)$/gm, '<li class="ml-4 list-disc">$1</li>')
      .replace(/^\d+\. (.+)$/gm, '<li class="ml-4 list-decimal">$1</li>')
      .replace(/\n\n/g, '<br/><br/>');
  }

  // Load health data
  async function loadHealth() {
    if (!id) return;
    setHealthLoading(true);
    try {
      const data = await getAssetHealth(Number(id));
      setHealthData(data);
    } catch {}
    setHealthLoading(false);
  }

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;
  if (!asset) return <div className="p-8 text-center text-slate-400">资产不存在</div>;

  const isWorkbook = asset.asset_type === 'workbook';
  const hasParent = asset.asset_type === 'view' || asset.asset_type === 'dashboard';

  // Build available tabs
  const tabs = [
    { key: 'info', label: '基本信息' },
    { key: 'datasources', label: '关联数据源' },
    ...(isWorkbook ? [{ key: 'children', label: `子视图 (${children.length})` }] : []),
    { key: 'fields', label: '字段元数据' },
    { key: 'health', label: '健康度' },
    { key: 'ai', label: 'AI 深度解读', warn: !llmConfigured },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-5xl mx-auto">
          {/* Breadcrumb */}
          <div className="flex items-center gap-2 text-sm text-slate-500 mb-4">
            <button onClick={() => navigate(-1)} className="hover:text-slate-700 flex items-center gap-1">
              <i className="ri-arrow-left-line" /> 返回
            </button>
            {hasParent && parentAsset && (
              <>
                <span className="text-slate-300">/</span>
                <Link to={`/tableau/assets/${parentAsset.id}`} className="hover:text-blue-600 flex items-center gap-1">
                  <i className={ASSET_TYPE_ICONS['workbook']} />
                  {parentAsset.name}
                </Link>
                <span className="text-slate-300">/</span>
                <span className="text-slate-700">{asset.name}</span>
              </>
            )}
            {hasParent && !parentAsset && asset.parent_workbook_name && (
              <>
                <span className="text-slate-300">/</span>
                <span className="text-slate-400 flex items-center gap-1">
                  <i className={ASSET_TYPE_ICONS['workbook']} />
                  {asset.parent_workbook_name}
                </span>
                <span className="text-slate-300">/</span>
                <span className="text-slate-700">{asset.name}</span>
              </>
            )}
          </div>

          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-xl font-semibold text-slate-800">{asset.name}</h1>
              <div className="flex items-center gap-3 mt-2">
                <span className={`px-2 py-0.5 rounded text-xs ${
                  asset.asset_type === 'workbook' ? 'bg-blue-50 text-blue-600' :
                  asset.asset_type === 'dashboard' ? 'bg-purple-50 text-purple-600' :
                  asset.asset_type === 'view' ? 'bg-emerald-50 text-emerald-600' :
                  'bg-orange-50 text-orange-600'
                }`}>
                  {ASSET_TYPE_LABELS[asset.asset_type] || asset.asset_type}
                </span>
                <span className="text-sm text-slate-400">{asset.project_name || '未分类'}</span>
                {asset.tags && (
                  <div className="flex items-center gap-1">
                    {asset.tags.split(',').map(tag => (
                      <span key={tag} className="text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">
                        {tag.trim()}
                      </span>
                    ))}
                  </div>
                )}
                {asset.health_score != null && (
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    asset.health_score >= 80 ? 'bg-emerald-50 text-emerald-600' :
                    asset.health_score >= 50 ? 'bg-yellow-50 text-yellow-600' :
                    'bg-red-50 text-red-600'
                  }`}>
                    健康度 {asset.health_score}
                  </span>
                )}
              </div>
            </div>
            {asset.content_url && (
              <span className="text-xs text-slate-400 bg-slate-100 px-2 py-1 rounded">
                ID: {asset.tableau_id}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-8 py-6">
        <div className="flex gap-6">
          {/* Main Content */}
          <div className="flex-1">
            {/* Tabs */}
            <div className="flex items-center gap-1 px-1 py-1 bg-slate-100 rounded-lg w-fit mb-6">
              {tabs.map(tab => (
                <button
                  key={tab.key}
                  onClick={() => {
                    setActiveTab(tab.key as typeof activeTab);
                    if (tab.key === 'ai' && !aiContent && !aiLoading) {
                      loadAIExplain();
                    }
                  }}
                  className={`px-4 py-1.5 rounded-md text-[12px] font-medium transition-colors cursor-pointer whitespace-nowrap ${
                    activeTab === tab.key ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {(tab as any).warn && <span className="mr-1 text-orange-400">!</span>}
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Tab: Info */}
            {activeTab === 'info' && (
              <div className="space-y-6">
                <div className="bg-white border border-slate-200 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-slate-700 mb-4">基本信息</h3>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <span className="text-slate-400">资产名称</span>
                      <p className="font-medium text-slate-800">{asset.name}</p>
                    </div>
                    <div>
                      <span className="text-slate-400">资产类型</span>
                      <p className="font-medium text-slate-800">{ASSET_TYPE_LABELS[asset.asset_type] || asset.asset_type}</p>
                    </div>
                    <div>
                      <span className="text-slate-400">项目</span>
                      <p className="font-medium text-slate-800">{asset.project_name || '-'}</p>
                    </div>
                    <div>
                      <span className="text-slate-400">所有者</span>
                      <p className="font-medium text-slate-800">{asset.owner_name || '-'}</p>
                    </div>
                    <div>
                      <span className="text-slate-400">Tableau ID</span>
                      <p className="font-mono text-xs text-slate-600">{asset.tableau_id}</p>
                    </div>
                    <div>
                      <span className="text-slate-400">同步时间</span>
                      <p className="text-slate-600">{asset.synced_at}</p>
                    </div>
                    {asset.created_on_server && (
                      <div>
                        <span className="text-slate-400">创建时间 (Server)</span>
                        <p className="text-slate-600">{asset.created_on_server}</p>
                      </div>
                    )}
                    {asset.updated_on_server && (
                      <div>
                        <span className="text-slate-400">更新时间 (Server)</span>
                        <p className="text-slate-600">{asset.updated_on_server}</p>
                      </div>
                    )}
                    {asset.view_count != null && (
                      <div>
                        <span className="text-slate-400">浏览次数</span>
                        <p className="font-medium text-slate-800">{asset.view_count.toLocaleString()}</p>
                      </div>
                    )}
                    {asset.sheet_type && (
                      <div>
                        <span className="text-slate-400">视图类型</span>
                        <p className="text-slate-600">{asset.sheet_type}</p>
                      </div>
                    )}
                    {asset.field_count != null && (
                      <div>
                        <span className="text-slate-400">字段数</span>
                        <p className="text-slate-600">{asset.field_count}</p>
                      </div>
                    )}
                    {asset.is_certified != null && (
                      <div>
                        <span className="text-slate-400">认证状态</span>
                        <p className={`font-medium ${asset.is_certified ? 'text-emerald-600' : 'text-slate-500'}`}>
                          {asset.is_certified ? '已认证' : '未认证'}
                        </p>
                      </div>
                    )}
                  </div>
                  {asset.description && (
                    <div className="mt-4 pt-4 border-t border-slate-100">
                      <span className="text-slate-400 text-sm">描述</span>
                      <p className="text-sm text-slate-700 mt-1">{asset.description}</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Tab: Datasources */}
            {activeTab === 'datasources' && (
              <div className="space-y-4">
                {asset.datasources && asset.datasources.length > 0 ? (
                  <div className="bg-white border border-slate-200 rounded-xl p-5">
                    <h3 className="text-sm font-semibold text-slate-700 mb-4">关联数据源</h3>
                    <div className="space-y-2">
                      {asset.datasources.map(ds => (
                        <div key={ds.id} className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg">
                          <i className="ri-database-2-line text-slate-400" />
                          <div>
                            <p className="text-sm font-medium text-slate-700">{ds.datasource_name}</p>
                            {ds.datasource_type && (
                              <p className="text-xs text-slate-400">{ds.datasource_type}</p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="bg-white border border-slate-200 rounded-xl p-5 text-center text-slate-400">
                    暂无关联数据源
                  </div>
                )}
              </div>
            )}

            {/* Tab: Children (workbooks only) */}
            {activeTab === 'children' && isWorkbook && (
              <div className="space-y-4">
                {childrenLoading ? (
                  <div className="text-center py-8 text-slate-400">
                    <i className="ri-loader-2-line animate-spin" /> 加载子视图...
                  </div>
                ) : children.length > 0 ? (
                  <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                    <table className="w-full">
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200">
                          <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">类型</th>
                          <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">名称</th>
                          <th className="text-left text-xs font-semibold text-slate-500 px-4 py-3">所有者</th>
                          <th className="text-right text-xs font-semibold text-slate-500 px-4 py-3">浏览次数</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {children.map(child => (
                          <tr key={child.id}
                            onClick={() => navigate(`/tableau/assets/${child.id}`)}
                            className="hover:bg-slate-50 cursor-pointer">
                            <td className="px-4 py-3">
                              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs ${
                                child.asset_type === 'dashboard' ? 'bg-purple-50 text-purple-600' :
                                'bg-emerald-50 text-emerald-600'
                              }`}>
                                <i className={ASSET_TYPE_ICONS[child.asset_type]} />
                                {ASSET_TYPE_LABELS[child.asset_type]}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-sm text-slate-800">{child.name}</td>
                            <td className="px-4 py-3 text-sm text-slate-500">{child.owner_name || '-'}</td>
                            <td className="px-4 py-3 text-sm text-slate-500 text-right">
                              {child.view_count != null ? child.view_count.toLocaleString() : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="bg-white border border-slate-200 rounded-xl p-5 text-center text-slate-400">
                    暂无子视图
                  </div>
                )}
              </div>
            )}

            {/* Tab: Field Metadata */}
            {activeTab === 'fields' && (
              <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <div className="px-5 py-4 border-b border-slate-100">
                  <h3 className="text-sm font-semibold text-slate-700">字段元数据</h3>
                  <p className="text-xs text-slate-400 mt-0.5">数据源字段信息（需先生成 AI 解读以加载字段）</p>
                </div>
                {fieldSemantics.length === 0 ? (
                  <div className="text-center py-10 text-slate-400 text-xs">
                    暂无字段数据，请先在 AI 解读 Tab 生成解读
                  </div>
                ) : (
                  <table className="w-full">
                    <thead>
                      <tr className="bg-slate-50">
                        {['字段名', '中文名', '数据类型', '角色', '描述'].map(h => (
                          <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {fieldSemantics.map((f: any, i: number) => (
                        <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                          <td className="px-4 py-2.5 text-xs font-mono text-slate-700">{f.field}</td>
                          <td className="px-4 py-2.5 text-xs text-slate-600">{f.caption || '-'}</td>
                          <td className="px-4 py-2.5 text-xs text-slate-500">{f.data_type || '-'}</td>
                          <td className="px-4 py-2.5">
                            <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                              f.role === 'measure' ? 'bg-blue-50 text-blue-600' : 'bg-slate-100 text-slate-600'
                            }`}>{f.role || '-'}</span>
                          </td>
                          <td className="px-4 py-2.5 text-xs text-slate-500 max-w-xs truncate">{f.meaning || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {/* Tab: Health */}
            {activeTab === 'health' && (
              <div className="space-y-4">
                <div className="bg-white border border-slate-200 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-semibold text-slate-700">健康度评估</h3>
                    <button
                      onClick={loadHealth}
                      disabled={healthLoading}
                      className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50"
                    >
                      <i className={healthLoading ? "ri-loader-2-line animate-spin mr-1" : "ri-refresh-line mr-1"} />
                      {healthData ? '重新评估' : '开始评估'}
                    </button>
                  </div>

                  {healthLoading ? (
                    <div className="text-center py-10 text-slate-400 text-sm">
                      <i className="ri-loader-2-line animate-spin text-xl block mb-2" />
                      评估中...
                    </div>
                  ) : !healthData ? (
                    <div className="text-center py-10">
                      <i className="ri-heart-pulse-line text-3xl text-slate-300 block mb-3" />
                      <div className="text-slate-400 text-sm mb-4">点击"开始评估"检查资产健康度</div>
                      <button onClick={loadHealth} className="px-5 py-2.5 text-sm bg-slate-900 text-white rounded-lg hover:bg-slate-800">
                        <i className="ri-heart-pulse-line mr-1" /> 开始评估
                      </button>
                    </div>
                  ) : (
                    <>
                      {/* Score header */}
                      <div className="flex items-center gap-6 mb-6 p-4 bg-slate-50 rounded-xl">
                        <div className={`text-4xl font-bold ${
                          healthData.score >= 80 ? 'text-emerald-600' :
                          healthData.score >= 60 ? 'text-amber-600' :
                          healthData.score >= 40 ? 'text-orange-600' : 'text-red-600'
                        }`}>{healthData.score}</div>
                        <div>
                          <div className="text-sm font-medium text-slate-700">
                            {healthData.level === 'excellent' ? '优秀' :
                             healthData.level === 'good' ? '良好' :
                             healthData.level === 'warning' ? '需改进' : '较差'}
                          </div>
                          <div className="text-xs text-slate-400">满分 100 · 基于 {healthData.checks.length} 项检查</div>
                        </div>
                      </div>

                      {/* Check items */}
                      <div className="space-y-2">
                        {healthData.checks.map((check) => (
                          <div key={check.key} className={`flex items-center justify-between p-3 rounded-lg border ${
                            check.passed ? 'bg-emerald-50 border-emerald-200' : 'bg-red-50 border-red-200'
                          }`}>
                            <div className="flex items-center gap-3">
                              <i className={check.passed ? 'ri-checkbox-circle-fill text-emerald-500' : 'ri-close-circle-fill text-red-500'} />
                              <div>
                                <div className="text-xs font-medium text-slate-700">{check.label}</div>
                                <div className="text-[11px] text-slate-500">{check.detail}</div>
                              </div>
                            </div>
                            <span className="text-[10px] text-slate-400 font-medium">{check.weight}%</span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* Tab: AI Deep Explain */}
            {activeTab === 'ai' && (
              <div className="space-y-4">
                <div className="bg-white border border-slate-200 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-700">AI 深度解读</h3>
                      <p className="text-xs text-slate-400 mt-0.5">基于元数据、数据源字段和层级关系的深度分析</p>
                    </div>
                    <button
                      onClick={handleRefreshAI}
                      disabled={aiLoading}
                      className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50 transition-colors"
                    >
                      <i className="ri-refresh-line mr-1" />
                      {aiContent ? '重新生成' : '生成解读'}
                    </button>
                  </div>

                  {aiLoading ? (
                    <div className="flex items-center justify-center py-12">
                      <div className="flex flex-col items-center gap-3 text-slate-400">
                        <i className="ri-loader-2-line animate-spin text-2xl" />
                        <span className="text-sm">正在调用 LLM 深度分析...</span>
                        <span className="text-xs text-slate-300">将分析元数据、数据源字段和关联关系</span>
                      </div>
                    </div>
                  ) : !llmConfigured ? (
                    <div className="text-center py-8">
                      <div className="text-orange-500 text-sm mb-2">LLM 未配置</div>
                      <p className="text-slate-500 text-xs mb-3">请联系管理员配置 LLM 后再试</p>
                      <a href="/admin/llm" className="text-sm text-blue-500 hover:underline">
                        去配置 LLM
                      </a>
                    </div>
                  ) : aiError ? (
                    <div className="text-center py-8">
                      <div className="text-red-500 text-sm mb-2">{aiError}</div>
                      <button onClick={() => loadAIExplain()} className="text-sm text-blue-500 hover:underline">
                        重试
                      </button>
                    </div>
                  ) : aiContent ? (
                    <div>
                      <div
                        className="prose prose-sm prose-slate max-w-none bg-slate-50 rounded-lg p-5 text-sm text-slate-700 leading-relaxed"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(aiContent) }}
                      />
                      {aiCached && (
                        <div className="mt-2 text-xs text-slate-400">
                          <i className="ri-checkbox-circle-line mr-1" />
                          已缓存，1 小时内不重复生成
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="text-center py-12">
                      <i className="ri-sparkling-line text-3xl text-slate-300 mb-3 block" />
                      <div className="text-slate-400 text-sm mb-4">点击生成 AI 深度解读</div>
                      <button
                        onClick={() => loadAIExplain()}
                        className="px-5 py-2.5 text-sm bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition-colors"
                      >
                        <i className="ri-sparkling-line mr-1" />
                        生成深度解读
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Sidebar */}
          <aside className="w-64 shrink-0 space-y-4">
            {/* Link */}
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">链接信息</h3>
              {asset.content_url && asset.server_url ? (
                <a
                  href={`${asset.server_url}/#/views${asset.content_url.replace('/views', '')}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-500 hover:underline break-all flex items-center gap-1"
                >
                  <i className="ri-external-link-line" />
                  在 Tableau Server 查看
                </a>
              ) : asset.content_url ? (
                <p className="text-xs text-slate-400 break-all">{asset.content_url}</p>
              ) : (
                <p className="text-xs text-slate-400">-</p>
              )}
            </div>

            {/* Parent Workbook */}
            {hasParent && (parentAsset || asset.parent_workbook_name) && (
              <div className="bg-white border border-slate-200 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-slate-700 mb-3">所属工作簿</h3>
                {parentAsset ? (
                  <Link to={`/tableau/assets/${parentAsset.id}`}
                    className="flex items-center gap-2 p-2 bg-blue-50 rounded-lg hover:bg-blue-100 transition-colors">
                    <i className="ri-file-chart-line text-blue-500" />
                    <span className="text-sm text-blue-700 font-medium truncate">{parentAsset.name}</span>
                  </Link>
                ) : (
                  <div className="flex items-center gap-2 p-2 bg-slate-50 rounded-lg">
                    <i className="ri-file-chart-line text-slate-400" />
                    <span className="text-sm text-slate-600 truncate">{asset.parent_workbook_name}</span>
                  </div>
                )}
              </div>
            )}

            {/* Quick Stats */}
            {(asset.view_count != null || asset.field_count != null || asset.health_score != null) && (
              <div className="bg-white border border-slate-200 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-slate-700 mb-3">统计概览</h3>
                <div className="space-y-3">
                  {asset.view_count != null && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-400">浏览次数</span>
                      <span className="text-sm font-medium text-slate-700">{asset.view_count.toLocaleString()}</span>
                    </div>
                  )}
                  {asset.field_count != null && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-400">字段数</span>
                      <span className="text-sm font-medium text-slate-700">{asset.field_count}</span>
                    </div>
                  )}
                  {asset.health_score != null && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-400">健康度</span>
                      <span className={`text-sm font-medium ${
                        asset.health_score >= 80 ? 'text-emerald-600' :
                        asset.health_score >= 50 ? 'text-yellow-600' :
                        'text-red-600'
                      }`}>
                        {asset.health_score}/100
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </aside>
        </div>
      </div>

      {/* 通用确认弹窗 */}
      {confirmModal && (
        <ConfirmModal
          open={confirmModal.open}
          title={confirmModal.title}
          message={confirmModal.message}
          confirmLabel="重新生成"
          onConfirm={confirmModal.onConfirm}
          onCancel={() => setConfirmModal(null)}
        />
      )}
    </div>
  );
}
