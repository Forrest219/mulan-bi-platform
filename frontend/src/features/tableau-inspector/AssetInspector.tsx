import { useNavigate, Link } from 'react-router-dom';
import { lazy, Suspense, useMemo } from 'react';
import { useAssetDetail } from './hooks/useAssetDetail';
import { InfoTab } from './tabs/InfoTab';
import { DatasourcesTab } from './tabs/DatasourcesTab';
import { ChildrenTab } from './tabs/ChildrenTab';
import { FieldsTab } from './tabs/FieldsTab';
import { HealthTab } from './tabs/HealthTab';
import { AiExplainTab } from './tabs/AiExplainTab';
import { ConfirmModal } from '../../components/ConfirmModal';
import { ASSET_TYPE_LABELS } from '../../config';
import { useHelpAgentSelection } from '../../pages/agents/help-agent/helpAgentContext';

// SPEC 40: ImpactTab 懒加载（仅 datasource 类型显示）
const ImpactTab = lazy(() =>
  import('./tabs/ImpactTab').then(m => ({ default: m.ImpactTab }))
);

const ASSET_TYPE_ICONS: Record<string, string> = {
  workbook: 'ri-file-chart-line',
  dashboard: 'ri-dashboard-line',
  view: 'ri-bar-chart-box-line',
  datasource: 'ri-database-2-line',
};

export interface AssetInspectorProps {
  assetId: string;
  layout?: 'page' | 'drawer';
  defaultTab?: string;
  onClose?: () => void;
}

export function AssetInspector({ assetId, layout = 'page', defaultTab, onClose }: AssetInspectorProps) {
  const navigate = useNavigate();
  const helpAgentSelection = useMemo(
    () => ({
      primary_entity: {
        type: 'tableau_asset',
        id: String(assetId),
        source: 'route' as const,
      },
    }),
    [assetId]
  );

  useHelpAgentSelection(helpAgentSelection);

  const {
    asset,
    loading,
    children,
    childrenLoading,
    parent,
    aiContent,
    aiLoading,
    aiError,
    aiCached,
    llmConfigured,
    handleRefreshAI,
    healthData,
    healthLoading,
    healthError,
    loadHealth,
    fieldSemantics,
    fieldMetadata,
    fieldsLoading,
    activeTab,
    setActiveTab,
    confirmModal,
    setConfirmModal,
    loadAIExplain,
  } = useAssetDetail(assetId, defaultTab);

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;
  if (!asset) return <div className="p-8 text-center text-slate-400">资产不存在</div>;

  const isWorkbook = asset.asset_type === 'workbook';
  const isDatasource = asset.asset_type === 'datasource';
  const hasParent = asset.asset_type === 'view' || asset.asset_type === 'dashboard';

  // Build available tabs
  const tabs = [
    { key: 'info', label: '基本信息' },
    { key: 'datasources', label: '关联数据源' },
    ...(isWorkbook ? [{ key: 'children', label: `子视图 (${children.length})` }] : []),
    { key: 'fields', label: '字段元数据' },
    { key: 'health', label: '健康度' },
    { key: 'ai', label: 'AI 深度解读', warn: !llmConfigured },
    ...(isDatasource ? [{ key: 'impact', label: '影响分析' }] : []),
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      {layout === 'page' && (
        <div className="bg-white border-b border-slate-200 px-6 py-5">
          <div className="max-w-6xl mx-auto">
            {/* Breadcrumb */}
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-4">
              <button onClick={() => navigate(-1)} className="hover:text-slate-700 flex items-center gap-1">
                <i className="ri-arrow-left-line" /> 返回
              </button>
              {hasParent && parent && (
                <>
                  <span className="text-slate-300">/</span>
                  <Link to={`/assets/tableau/${parent.id}`} className="hover:text-blue-600 flex items-center gap-1">
                    <i className={ASSET_TYPE_ICONS['workbook']} />
                    {parent.name}
                  </Link>
                  <span className="text-slate-300">/</span>
                  <span className="text-slate-700">{asset.name}</span>
                </>
              )}
              {hasParent && !parent && asset.parent_workbook_name && (
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
                <h1 className="text-sm font-semibold text-slate-800">{asset.name}</h1>
                <div className="flex items-center gap-3 mt-1.5">
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    asset.asset_type === 'workbook' ? 'bg-blue-50 text-blue-600' :
                    asset.asset_type === 'dashboard' ? 'bg-purple-50 text-purple-600' :
                    asset.asset_type === 'view' ? 'bg-emerald-50 text-emerald-600' :
                    'bg-orange-50 text-orange-600'
                  }`}>
                    {ASSET_TYPE_LABELS[asset.asset_type] || asset.asset_type}
                  </span>
                  <span className="text-xs text-slate-400">{asset.project_name || '未分类'}</span>
                  {Array.isArray(asset.tags) && asset.tags.length > 0 && (
                    <div className="flex items-center gap-1">
                      {asset.tags.map(tag => (
                        <span key={tag} className="text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">
                          {tag}
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
      )}

      {/* Drawer header */}
      {layout === 'drawer' && (
        <div className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-800">{asset.name}</h2>
            <span className="text-xs text-slate-400">{ASSET_TYPE_LABELS[asset.asset_type] || asset.asset_type}</span>
          </div>
          {onClose && (
            <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
              <i className="ri-close-line text-xl" />
            </button>
          )}
        </div>
      )}

      <div className="max-w-6xl mx-auto px-6 py-8">
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

        <div className="flex gap-6">
          {/* Main Content */}
          <div className="flex-1">

            {/* Tab: Info */}
            {activeTab === 'info' && (
              <InfoTab asset={asset} parent={parent} />
            )}

            {/* Tab: Datasources */}
            {activeTab === 'datasources' && (
              <DatasourcesTab asset={asset} datasources={asset.datasources} />
            )}

            {/* Tab: Children (workbooks only) */}
            {activeTab === 'children' && isWorkbook && (
              <ChildrenTab children={children} childrenLoading={childrenLoading} />
            )}

            {/* Tab: Field Metadata */}
            {activeTab === 'fields' && (
              <FieldsTab fieldSemantics={fieldSemantics} fieldMetadata={fieldMetadata} fieldsLoading={fieldsLoading} />
            )}

            {/* Tab: Health */}
            {activeTab === 'health' && (
              <HealthTab
                healthData={healthData}
                healthLoading={healthLoading}
                healthError={healthError}
                onLoad={loadHealth}
                assetName={asset.name}
                assetId={String(asset.id)}
              />
            )}

            {/* Tab: AI Deep Explain */}
            {activeTab === 'ai' && (
              <AiExplainTab
                aiContent={aiContent}
                aiLoading={aiLoading}
                aiError={aiError}
                aiCached={aiCached}
                onRefresh={handleRefreshAI}
                onLoadExplain={() => loadAIExplain()}
                llmConfigured={llmConfigured}
              />
            )}

            {/* Tab: Impact Analysis (datasource only) */}
            {activeTab === 'impact' && isDatasource && (
              <Suspense fallback={<div className="flex items-center justify-center py-12 text-slate-400 text-xs">加载中...</div>}>
                <ImpactTab assetId={String(asset.id)} />
              </Suspense>
            )}
          </div>

          {/* Sidebar */}
          <aside className="w-64 shrink-0 space-y-4">
            {/* Link */}
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <h3 className="text-xs font-semibold text-slate-700 mb-3">链接信息</h3>
              {asset.content_url && asset.server_url ? (
                <a
                  href={`${asset.server_url}/#${asset.site ? `/site/${asset.site}` : ''}${asset.content_url}`}
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
            {hasParent && (parent || asset.parent_workbook_name) && (
              <div className="bg-white border border-slate-200 rounded-xl p-5">
                <h3 className="text-xs font-semibold text-slate-700 mb-3">所属工作簿</h3>
                {parent ? (
                  <Link to={`/assets/tableau/${parent.id}`}
                    className="flex items-center gap-2 p-2 bg-blue-50 rounded-lg hover:bg-blue-100 transition-colors">
                    <i className="ri-file-chart-line text-blue-500" />
                    <span className="text-xs text-blue-700 font-medium truncate">{parent.name}</span>
                  </Link>
                ) : (
                  <div className="flex items-center gap-2 p-2 bg-slate-50 rounded-lg">
                    <i className="ri-file-chart-line text-slate-400" />
                    <span className="text-xs text-slate-600 truncate">{asset.parent_workbook_name}</span>
                  </div>
                )}
              </div>
            )}

            {/* MCP 调试 */}
            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <h3 className="text-xs font-semibold text-slate-700 mb-3">MCP 调试</h3>
              {asset.asset_type === 'workbook' && (
                <button
                  onClick={() => navigate(`/system/mcp-debugger?view=debugger&tool=get-workbook&arg_workbook_id=${asset.tableau_id}`)}
                  className="w-full text-left px-3 py-2 text-xs text-blue-600 hover:bg-blue-50 rounded-lg flex items-center gap-2 transition-colors"
                >
                  <i className="ri-bug-line" /> 调试 get-workbook
                </button>
              )}
              {asset.asset_type === 'datasource' && (
                <button
                  onClick={() => navigate(`/system/mcp-debugger?view=debugger&tool=get-datasource-metadata&arg_datasource_luid=${asset.tableau_id}`)}
                  className="w-full text-left px-3 py-2 text-xs text-blue-600 hover:bg-blue-50 rounded-lg flex items-center gap-2 transition-colors"
                >
                  <i className="ri-bug-line" /> 调试 get-datasource-metadata
                </button>
              )}
              {(asset.asset_type === 'view' || asset.asset_type === 'dashboard') && (
                <>
                  <button
                    onClick={() => navigate(`/system/mcp-debugger?view=debugger&tool=get-view-data&arg_view_id=${asset.tableau_id}`)}
                    className="w-full text-left px-3 py-2 text-xs text-blue-600 hover:bg-blue-50 rounded-lg flex items-center gap-2 transition-colors"
                  >
                    <i className="ri-bug-line" /> 调试 get-view-data
                  </button>
                  {parent && (
                    <button
                      onClick={() => navigate(`/system/mcp-debugger?view=debugger&tool=list-views&arg_workbook_id=${parent.tableau_id}`)}
                      className="w-full text-left px-3 py-2 text-xs text-blue-600 hover:bg-blue-50 rounded-lg flex items-center gap-2 transition-colors"
                    >
                      <i className="ri-bug-line" /> 调试 list-views
                    </button>
                  )}
                </>
              )}
            </div>
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
