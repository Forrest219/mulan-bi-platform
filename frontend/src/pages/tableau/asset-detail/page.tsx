import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getAsset, TableauAsset } from '../../../api/tableau';
import { getAssetSummary, getLLMConfig } from '../../../api/llm';

const ASSET_TYPE_LABELS: Record<string, string> = {
  workbook: '工作簿',
  dashboard: '仪表板',
  view: '视图',
  datasource: '数据源'
};

export default function TableauAssetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [asset, setAsset] = useState<TableauAsset | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'info' | 'datasources' | 'ai'>('info');
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiCached, setAiCached] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState(true);

  useEffect(() => {
    if (!id) return;
    getAsset(Number(id))
      .then(setAsset)
      .catch(console.error)
      .finally(() => setLoading(false));
    // 检查 LLM 是否已配置
    getLLMConfig().then(d => {
      setLlmConfigured(!!d.config && d.config.is_active);
    }).catch(() => setLlmConfigured(false));
  }, [id]);

  async function loadAISummary(refresh = false) {
    if (!id) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const result = await getAssetSummary(Number(id), refresh);
      setAiSummary(result.summary);
      setAiError(result.error || null);
      setAiCached(result.cached);
    } catch (e: any) {
      setAiError(e.message || '获取摘要失败');
    } finally {
      setAiLoading(false);
    }
  }

  function handleRefreshSummary() {
    if (aiSummary) {
      if (confirm('确定要重新生成解读吗？')) {
        loadAISummary(true);
      }
    } else {
      loadAISummary(false);
    }
  }

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;
  if (!asset) return <div className="p-8 text-center text-slate-400">资产不存在</div>;

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-5xl mx-auto">
          <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 mb-4">
            <i className="ri-arrow-left-line" /> 返回
          </button>
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
        {/* Tabs */}
        <div className="flex items-center gap-1 px-1 py-1 bg-slate-100 rounded-lg w-fit mb-6">
          {[
            { key: 'info', label: '基本信息' },
            { key: 'datasources', label: '关联数据源' },
            { key: 'ai', label: 'AI 解读', warn: !llmConfigured },
          ].map(tab => (
            <button
              key={tab.key}
              onClick={() => {
                setActiveTab(tab.key as typeof activeTab);
                if (tab.key === 'ai' && !aiSummary && !aiLoading) {
                  loadAISummary();
                }
              }}
              className={`px-4 py-1.5 rounded-md text-[12px] font-medium transition-colors cursor-pointer whitespace-nowrap ${
                activeTab === tab.key ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {(tab as any).warn && <span className="mr-1 text-orange-400">⚠️</span>}
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        {activeTab === 'info' && (
          <div className="grid grid-cols-3 gap-6">
            <div className="col-span-2 space-y-6">
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
                </div>
                {asset.description && (
                  <div className="mt-4 pt-4 border-t border-slate-100">
                    <span className="text-slate-400 text-sm">描述</span>
                    <p className="text-sm text-slate-700 mt-1">{asset.description}</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

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

        {activeTab === 'ai' && (
          <div className="space-y-4">
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-slate-700">AI 解读</h3>
                <button
                  onClick={handleRefreshSummary}
                  disabled={aiLoading}
                  className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50 transition-colors"
                >
                  <i className="ri-refresh-line mr-1" />
                  {aiSummary ? '刷新解读' : '生成解读'}
                </button>
              </div>

              {aiLoading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="flex items-center gap-2 text-slate-400">
                    <i className="ri-loader-2-line animate-spin" />
                    <span className="text-sm">正在生成解读...</span>
                  </div>
                </div>
              ) : !llmConfigured ? (
                <div className="text-center py-8">
                  <div className="text-orange-500 text-sm mb-2">⚠️ LLM 未配置</div>
                  <p className="text-slate-500 text-xs mb-3">请联系管理员配置 LLM 后再试</p>
                  <a href="/admin/llm" className="text-sm text-blue-500 hover:underline">
                    去配置 LLM →
                  </a>
                </div>
              ) : aiError ? (
                <div className="text-center py-8">
                  <div className="text-red-500 text-sm mb-2">⚠️ {aiError}</div>
                  <button
                    onClick={() => loadAISummary()}
                    className="text-sm text-blue-500 hover:underline"
                  >
                    重试
                  </button>
                </div>
              ) : aiSummary ? (
                <div>
                  <div className="bg-slate-50 rounded-lg p-4 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
                    {aiSummary}
                  </div>
                  {aiCached && (
                    <div className="mt-2 text-xs text-slate-400">
                      <i className="ri-checkbox-circle-line mr-1" />
                      已缓存，1 小时内不重复生成
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center py-8">
                  <div className="text-slate-400 text-sm mb-3">暂无解读内容</div>
                  <button
                    onClick={() => loadAISummary()}
                    className="px-4 py-2 text-sm bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
                  >
                    生成 AI 解读
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Sidebar */}
        <aside className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-4">链接信息</h3>
            {asset.content_url && asset.server_url ? (
              <a
                href={`${asset.server_url}/#/views${asset.content_url.replace('/views', '')}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-500 hover:underline break-all"
              >
                在 Tableau Server 查看 →
              </a>
            ) : asset.content_url ? (
              <p className="text-xs text-slate-400 break-all">{asset.content_url}</p>
            ) : (
              <p className="text-xs text-slate-400">-</p>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
