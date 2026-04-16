import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getDatasourceSemantics, updateDatasourceSemantics,
  submitDatasourceForReview, approveDatasource, rejectDatasource,
  generateDatasourceAI, getDatasourceVersions, rollbackDatasource,
  getStatusBadge, getSensitivityBadge, publishDatasource, previewDatasourceDiff,
  listPublishLogs, SemanticDatasource, SemanticVersion, PublishLog, SensitivityLevel,
} from '../../../api/semantic-maintenance';
import { ConfirmModal } from '../../../components/ConfirmModal';

type Tab = 'metadata' | 'semantic' | 'publish';
type DatasourceDiffPreview = {
  tableau_current?: unknown;
  mulan_pending?: unknown;
  diff?: Record<string, unknown>;
};

type ActionResult = { message?: string };

const getErrorMessage = (error: unknown, fallback = '操作失败'): string => {
  return error instanceof Error ? error.message : fallback;
};

export default function SemanticDatasourceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [ds, setDs] = useState<SemanticDatasource | null>(null);
  const [versions, setVersions] = useState<SemanticVersion[]>([]);
  const [publishLogs, setPublishLogs] = useState<PublishLog[]>([]);
  const [activeTab, setActiveTab] = useState<Tab>('metadata');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [modalNotify, setModalNotify] = useState<{ success: boolean; message: string } | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean; title: string; message: string;
    confirmLabel?: string; variant?: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  } | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState<Partial<SemanticDatasource>>({});
  const [showDiff, setShowDiff] = useState<{ open: boolean; diff: DatasourceDiffPreview } | null>(null);
  const [generatingAI, setGeneratingAI] = useState(false);
  const [logsPage, setLogsPage] = useState(1);
  const [, setLogsTotal] = useState(0);
  const [logsPages, setLogsPages] = useState(1);

  const dsId = parseInt(id || '0', 10);

  /* eslint-disable react-hooks/exhaustive-deps -- loadData 在 dsId 变化时调用，故意不放入 deps */
  useEffect(() => {
    if (!dsId) return;
    loadData();
  }, [dsId]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [dsData, versionsData] = await Promise.all([
        getDatasourceSemantics(dsId),
        getDatasourceVersions(dsId),
      ]);
      setDs(dsData);
      setVersions(versionsData.versions);
      setEditForm({
        semantic_name_zh: dsData.semantic_name_zh,
        semantic_description: dsData.semantic_description,
        metric_definition: dsData.metric_definition,
        dimension_definition: dsData.dimension_definition,
        sensitivity_level: dsData.sensitivity_level,
      });
    } catch (e: unknown) {
      setError(getErrorMessage(e, '加载失败'));
    } finally {
      setLoading(false);
    }
  };

  const loadPublishLogs = async (page = 1) => {
    if (!ds) return;
    try {
      const data = await listPublishLogs(ds.connection_id, {
        object_type: 'datasource',
        page,
        page_size: 20,
      });
      // Filter to this datasource
      const filtered = data.items.filter(l => l.object_id === dsId);
      setPublishLogs(filtered);
      setLogsTotal(data.total);
      setLogsPages(Math.ceil(data.total / 20));
      setLogsPage(page);
    } catch (_e) {
      // silent fail for logs
    }
  };

  /* eslint-disable react-hooks/exhaustive-deps -- loadPublishLogs 依赖 ds，故意不放入 deps */
  useEffect(() => {
    if (activeTab === 'publish' && ds) {
      loadPublishLogs();
    }
  }, [activeTab, ds]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const handleAction = async (_action: string, fn: (id: number) => Promise<ActionResult>, successMsg: string) => {
    setActionLoading(true);
    try {
      const result = await fn(dsId);
      setModalNotify({ success: true, message: result.message || successMsg });
      loadData();
    } catch (e: unknown) {
      setModalNotify({ success: false, message: getErrorMessage(e) });
    } finally {
      setActionLoading(false);
    }
  };

  const handleSaveEdit = async () => {
    setActionLoading(true);
    try {
      const result = await updateDatasourceSemantics(dsId, editForm);
      setModalNotify({ success: true, message: result.message });
      setIsEditing(false);
      loadData();
    } catch (e: unknown) {
      setModalNotify({ success: false, message: getErrorMessage(e) });
    } finally {
      setActionLoading(false);
    }
  };

  const handleGenerateAI = async () => {
    setGeneratingAI(true);
    try {
      const result = await generateDatasourceAI(dsId);
      setModalNotify({ success: true, message: result.message });
      loadData();
    } catch (e: unknown) {
      setModalNotify({ success: false, message: getErrorMessage(e) });
    } finally {
      setGeneratingAI(false);
    }
  };

  const handleRollback = async (versionId: number) => {
    try {
      const result = await rollbackDatasource(dsId, versionId);
      setModalNotify({ success: true, message: result.message });
      loadData();
    } catch (e: unknown) {
      setModalNotify({ success: false, message: getErrorMessage(e) });
    }
  };

  const handlePreviewDiff = async () => {
    if (!ds) return;
    try {
      const diff = await previewDatasourceDiff(ds.connection_id, dsId);
      setShowDiff({ open: true, diff });
    } catch (e: unknown) {
      setModalNotify({ success: false, message: getErrorMessage(e) });
    }
  };

  const handlePublish = async (simulate = false) => {
    if (!ds) return;
    try {
      const result = await publishDatasource(ds.connection_id, dsId, simulate);
      setModalNotify({
        success: true,
        message: simulate ? '模拟发布完成' : (result.message || '发布成功'),
      });
      if (!simulate) loadData();
    } catch (e: unknown) {
      setModalNotify({ success: false, message: getErrorMessage(e) });
    }
  };

  const formatDate = (str: string | null) => str ? new Date(str).toLocaleString() : '-';

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;
  if (error) return <div className="p-8 text-center text-red-500">{error}</div>;
  if (!ds) return <div className="p-8 text-center text-slate-400">数据不存在</div>;

  const statusBadge = getStatusBadge(ds.status);
  const sensBadge = getSensitivityBadge(ds.sensitivity_level);

  const tabs: { key: Tab; label: string }[] = [
    { key: 'metadata', label: '原始元数据' },
    { key: 'semantic', label: '语义治理' },
    { key: 'publish', label: '发布记录' },
  ];

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/semantic-maintenance/datasources')}
            className="p-2 hover:bg-slate-100 rounded-lg">
            <i className="ri-arrow-left-line text-slate-500" />
          </button>
          <div>
            <h1 className="text-xl font-semibold text-slate-800">
              {ds.semantic_name_zh || `数据源 ${ds.id}`}
            </h1>
            <p className="text-sm text-slate-400 mt-0.5 font-mono">{ds.tableau_datasource_id}</p>
          </div>
          <div className="flex items-center gap-2 ml-4">
            <span className={`text-xs px-2 py-0.5 rounded-full ${statusBadge.className}`}>{statusBadge.text}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${sensBadge.className}`}>{sensBadge.text}</span>
            {ds.published_to_tableau && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600">已发布</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {ds.status === 'draft' || ds.status === 'ai_generated' || ds.status === 'rejected' ? (
            <button onClick={() => handleAction('submit', submitDatasourceForReview, '已提交审核')}
              disabled={actionLoading}
              className="px-4 py-2 text-sm bg-amber-50 hover:bg-amber-100 text-amber-600 rounded-lg flex items-center gap-1.5">
              <i className="ri-send-plane-line" /> 提交审核
            </button>
          ) : null}
          {ds.status === 'reviewed' ? (
            <>
              <button onClick={() => handleAction('approve', approveDatasource, '已审核通过')}
                disabled={actionLoading}
                className="px-4 py-2 text-sm bg-emerald-50 hover:bg-emerald-100 text-emerald-600 rounded-lg flex items-center gap-1.5">
                <i className="ri-check-line" /> 通过
              </button>
              <button onClick={() => setConfirmModal({
                open: true, title: '驳回数据源', message: '确定要驳回此数据源吗？',
                confirmLabel: '驳回', variant: 'warning',
                onConfirm: () => { setConfirmModal(null); handleAction('reject', rejectDatasource, '已驳回'); },
              })}
                disabled={actionLoading}
                className="px-4 py-2 text-sm bg-red-50 hover:bg-red-100 text-red-600 rounded-lg flex items-center gap-1.5">
                <i className="ri-close-line" /> 驳回
              </button>
            </>
          ) : null}
          {ds.status === 'approved' ? (
            <>
              <button onClick={handlePreviewDiff}
                className="px-4 py-2 text-sm bg-purple-50 hover:bg-purple-100 text-purple-600 rounded-lg flex items-center gap-1.5">
                <i className="ri-file-search-line" /> 差异预览
              </button>
              <button onClick={() => handlePublish(true)}
                className="px-4 py-2 text-sm bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg flex items-center gap-1.5">
                <i className="ri-eye-line" /> 模拟发布
              </button>
              <button onClick={() => setConfirmModal({
                open: true, title: '发布数据源',
                message: `确定要发布到 Tableau 吗？`,
                confirmLabel: '发布', variant: 'info',
                onConfirm: () => { setConfirmModal(null); handlePublish(false); },
              })}
                className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg flex items-center gap-1.5">
                <i className="ri-upload-cloud-line" /> 发布
              </button>
            </>
          ) : null}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-slate-200 mb-6">
        {tabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'metadata' && (
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">基本信息</h2>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div className="space-y-3">
              <div><span className="text-slate-400">ID:</span> <span className="text-slate-700">{ds.id}</span></div>
              <div><span className="text-slate-400">连接 ID:</span> <span className="text-slate-700">{ds.connection_id}</span></div>
              <div><span className="text-slate-400">Tableau ID:</span> <span className="text-slate-700 font-mono text-xs">{ds.tableau_datasource_id}</span></div>
              <div><span className="text-slate-400">字段注册 ID:</span> <span className="text-slate-700">{ds.field_registry_id || '-'}</span></div>
            </div>
            <div className="space-y-3">
              <div><span className="text-slate-400">创建时间:</span> <span className="text-slate-700">{formatDate(ds.created_at)}</span></div>
              <div><span className="text-slate-400">更新时间:</span> <span className="text-slate-700">{formatDate(ds.updated_at)}</span></div>
              <div><span className="text-slate-400">发布状态:</span> <span className="text-slate-700">{ds.published_to_tableau ? '已发布' : '未发布'}</span></div>
              <div><span className="text-slate-400">发布时间:</span> <span className="text-slate-700">{formatDate(ds.published_at)}</span></div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'semantic' && (
        <div className="space-y-6">
          {/* Semantic Info Card */}
          <div className="bg-white border border-slate-200 rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-slate-700">语义信息</h2>
              {!isEditing ? (
                <button onClick={() => setIsEditing(true)}
                  className="px-3 py-1.5 text-xs text-blue-600 hover:bg-blue-50 rounded-lg flex items-center gap-1">
                  <i className="ri-edit-line" /> 编辑
                </button>
              ) : (
                <div className="flex items-center gap-2">
                  <button onClick={() => { setIsEditing(false); setEditForm({
                    semantic_name_zh: ds.semantic_name_zh,
                    semantic_description: ds.semantic_description,
                    metric_definition: ds.metric_definition,
                    dimension_definition: ds.dimension_definition,
                    sensitivity_level: ds.sensitivity_level,
                  }); }}
                    className="px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100 rounded-lg">
                    取消
                  </button>
                  <button onClick={handleSaveEdit}
                    disabled={actionLoading}
                    className="px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg">
                    保存
                  </button>
                </div>
              )}
            </div>

            {isEditing ? (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">语义名称（中文）</label>
                  <input type="text" value={editForm.semantic_name_zh || ''}
                    onChange={e => setEditForm({ ...editForm, semantic_name_zh: e.target.value })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">语义描述</label>
                  <textarea value={editForm.semantic_description || ''}
                    onChange={e => setEditForm({ ...editForm, semantic_description: e.target.value })}
                    rows={3}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">指标定义</label>
                  <textarea value={editForm.metric_definition || ''}
                    onChange={e => setEditForm({ ...editForm, metric_definition: e.target.value })}
                    rows={2}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">维度定义</label>
                  <textarea value={editForm.dimension_definition || ''}
                    onChange={e => setEditForm({ ...editForm, dimension_definition: e.target.value })}
                    rows={2}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">敏感级别</label>
                  <select value={editForm.sensitivity_level || ''}
                    onChange={e => setEditForm({ ...editForm, sensitivity_level: e.target.value as SensitivityLevel })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500">
                    <option value="">未设置</option>
                    <option value="low">低</option>
                    <option value="medium">中</option>
                    <option value="high">高</option>
                    <option value="confidential">机密</option>
                  </select>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div className="space-y-3">
                  <div><span className="text-slate-400">语义名称:</span> <span className="text-slate-700">{ds.semantic_name_zh || '-'}</span></div>
                  <div><span className="text-slate-400">英文名称:</span> <span className="text-slate-700">{ds.semantic_name || '-'}</span></div>
                  <div><span className="text-slate-400">敏感级别:</span> <span className={`text-xs px-2 py-0.5 rounded-full ${sensBadge.className}`}>{sensBadge.text}</span></div>
                </div>
                <div className="space-y-3">
                  <div><span className="text-slate-400">指标定义:</span> <span className="text-slate-700 font-mono text-xs">{ds.metric_definition || '-'}</span></div>
                  <div><span className="text-slate-400">维度定义:</span> <span className="text-slate-700">{ds.dimension_definition || '-'}</span></div>
                  <div><span className="text-slate-400">语义描述:</span> <span className="text-slate-700">{ds.semantic_description || '-'}</span></div>
                </div>
              </div>
            )}
          </div>

          {/* AI Generation */}
          <div className="bg-white border border-slate-200 rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-slate-700">AI 语义生成</h2>
              <button
                onClick={handleGenerateAI}
                disabled={generatingAI}
                className="px-4 py-2 text-sm bg-violet-50 hover:bg-violet-100 text-violet-600 rounded-lg flex items-center gap-1.5 disabled:opacity-50">
                {generatingAI ? (
                  <><i className="ri-loader-4-line animate-spin" /> 生成中...</>
                ) : (
                  <><i className="ri-robot-line" /> AI 生成语义</>
                )}
              </button>
            </div>
            <p className="text-xs text-slate-400">基于数据源元数据自动生成语义描述和分类建议</p>
          </div>

          {/* Version History */}
          <div className="bg-white border border-slate-200 rounded-xl p-6">
            <h2 className="text-sm font-semibold text-slate-700 mb-4">版本历史</h2>
            {versions.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-4">暂无版本记录</p>
            ) : (
              <div className="space-y-2">
                {versions.map(v => (
                  <div key={v.id} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg text-sm">
                    <div>
                      <span className="text-slate-600">版本 {v.version_num}</span>
                      <span className="text-slate-400 mx-2">·</span>
                      <span className="text-slate-500">{formatDate(v.changed_at)}</span>
                      {v.change_summary && <span className="text-slate-400 mx-2">· {v.change_summary}</span>}
                    </div>
                    <button
                      onClick={() => setConfirmModal({
                        open: true, title: `回滚到版本 ${v.version_num}`,
                        message: '确定要回滚到此版本吗？当前版本将被覆盖。',
                        confirmLabel: '回滚', variant: 'warning',
                        onConfirm: () => { setConfirmModal(null); handleRollback(v.id); },
                      })}
                      className="px-2 py-1 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-200 rounded">
                      回滚
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === 'publish' && (
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">发布日志</h2>
          {publishLogs.length === 0 ? (
            <p className="text-sm text-slate-400 text-center py-8">暂无发布记录</p>
          ) : (
            <>
              <div className="space-y-2">
                {publishLogs.map(log => (
                  <div key={log.id} className="p-4 border border-slate-100 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${
                          log.status === 'success' ? 'bg-emerald-50 text-emerald-600' :
                          log.status === 'failed' ? 'bg-red-50 text-red-600' :
                          log.status === 'rolled_back' ? 'bg-slate-100 text-slate-600' :
                          'bg-amber-50 text-amber-600'
                        }`}>
                          {log.status === 'success' ? '成功' : log.status === 'failed' ? '失败' : log.status === 'rolled_back' ? '已回滚' : '进行中'}
                        </span>
                        <span className="text-xs text-slate-400">{formatDate(log.created_at)}</span>
                      </div>
                      <span className="text-xs text-slate-400">操作人 ID: {log.operator}</span>
                    </div>
                    {log.diff_json && (
                      <pre className="text-xs text-slate-500 bg-slate-50 p-2 rounded overflow-auto">
                        {JSON.stringify(JSON.parse(log.diff_json), null, 2)}
                      </pre>
                    )}
                    {log.error_message && (
                      <p className="text-xs text-red-500 mt-1">错误: {log.error_message}</p>
                    )}
                  </div>
                ))}
              </div>
              {logsPages > 1 && (
                <div className="flex items-center justify-center gap-2 mt-4">
                  <button onClick={() => loadPublishLogs(logsPage - 1)} disabled={logsPage <= 1}
                    className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg disabled:opacity-50">
                    上一页
                  </button>
                  <span className="text-sm text-slate-500">第 {logsPage} / {logsPages} 页</span>
                  <button onClick={() => loadPublishLogs(logsPage + 1)} disabled={logsPage >= logsPages}
                    className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg disabled:opacity-50">
                    下一页
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Diff Preview Modal */}
      {showDiff && showDiff.open && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-2xl shadow-xl max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-slate-800 mb-4">发布差异预览</h2>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 bg-slate-50 rounded-lg">
                  <h3 className="text-sm font-medium text-slate-600 mb-2">Tableau 当前值</h3>
                  <pre className="text-xs text-slate-500 overflow-auto">
                    {JSON.stringify(showDiff.diff.tableau_current, null, 2)}
                  </pre>
                </div>
                <div className="p-4 bg-blue-50 rounded-lg">
                  <h3 className="text-sm font-medium text-blue-600 mb-2">Mulan 待发布值</h3>
                  <pre className="text-xs text-blue-700 overflow-auto">
                    {JSON.stringify(showDiff.diff.mulan_pending, null, 2)}
                  </pre>
                </div>
              </div>
              {Object.keys(showDiff.diff.diff || {}).length > 0 ? (
                <div className="p-4 bg-amber-50 rounded-lg">
                  <h3 className="text-sm font-medium text-amber-600 mb-2">差异内容</h3>
                  <pre className="text-xs text-amber-700 overflow-auto">
                    {JSON.stringify(showDiff.diff.diff, null, 2)}
                  </pre>
                </div>
              ) : (
                <div className="p-4 bg-emerald-50 rounded-lg text-sm text-emerald-600">
                  无差异，值已同步
                </div>
              )}
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowDiff(null)}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700">关闭</button>
            </div>
          </div>
        </div>
      )}

      {/* Notification Toast */}
      {modalNotify && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-[60]" onClick={() => setModalNotify(null)}>
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-start gap-3">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center ${modalNotify.success ? 'bg-emerald-100' : 'bg-red-100'}`}>
                <i className={`${modalNotify.success ? 'ri-check-line text-emerald-600' : 'ri-error-warning-line text-red-600'} text-xl`} />
              </div>
              <div className="flex-1">
                <h3 className={`font-semibold ${modalNotify.success ? 'text-emerald-700' : 'text-red-700'}`}>
                  {modalNotify.success ? '操作成功' : '操作失败'}
                </h3>
                <p className="text-sm text-slate-600 mt-1">{modalNotify.message}</p>
              </div>
            </div>
            <button onClick={() => setModalNotify(null)}
              className="mt-4 w-full py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-medium rounded-lg">
              关闭
            </button>
          </div>
        </div>
      )}

      {/* Confirm Modal */}
      {confirmModal && confirmModal.open && (
        <ConfirmModal
          open={confirmModal.open}
          title={confirmModal.title}
          message={confirmModal.message}
          confirmLabel={confirmModal.confirmLabel}
          variant={confirmModal.variant}
          onConfirm={confirmModal.onConfirm}
          onCancel={() => setConfirmModal(null)}
        />
      )}
    </div>
  );
}