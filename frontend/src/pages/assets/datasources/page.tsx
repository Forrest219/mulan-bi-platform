import { useState, useEffect } from 'react';
import {
  listDataSources, createDataSource, updateDataSource, deleteDataSource,
  testDataSource, testDatasourceDraft, parseDatasourceConfig,
  DataSource, DB_TYPE_OPTIONS, DB_TYPE_PORT_DEFAULTS
} from '../../../api/datasources';
import { ConfirmModal } from '../../../components/ConfirmModal';

export default function DatasourcesPage() {
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Form view state
  const [showForm, setShowForm] = useState(false);
  const [editingDs, setEditingDs] = useState<DataSource | null>(null);
  const [formData, setFormData] = useState({
    name: '', db_type: 'mysql', host: '', port: 3306,
    database_name: '', username: '', password: '', description: '',
  });
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  // Test in form
  const [formTesting, setFormTesting] = useState(false);
  const [formTestResult, setFormTestResult] = useState<{ success: boolean; message: string } | null>(null);

  // List actions
  const [testingId, setTestingId] = useState<number | null>(null);
  const [modalNotify, setModalNotify] = useState<{ success: boolean; message: string } | null>(null);
  const [confirmModal, setConfirmModal] = useState<{ open: boolean; title: string; message: string; onConfirm: () => void } | null>(null);

  // AI Parse
  const [pasteText, setPasteText] = useState('');
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsed, setParsed] = useState(false);

  const fetchDatasources = async () => {
    try {
      const data = await listDataSources();
      setDatasources(data.datasources);
    } catch (e: unknown) {
      setLoadError(e instanceof Error ? e.message : '加载失败，请检查是否已登录');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDatasources(); }, []);

  const resetForm = () => {
    setFormData({ name: '', db_type: 'mysql', host: '', port: 3306, database_name: '', username: '', password: '', description: '' });
    setFormError('');
    setEditingDs(null);
    setFormTestResult(null);
    setFormTesting(false);
    setPasteText('');
    setParseError(null);
    setParsed(false);
  };

  const handleOpenNew = () => {
    resetForm();
    setShowForm(true);
  };

  const handleOpenEdit = (ds: DataSource) => {
    setEditingDs(ds);
    setFormData({
      name: ds.name, db_type: ds.db_type, host: ds.host, port: ds.port,
      database_name: ds.database_name, username: ds.username, password: '',
      description: ds.description ?? '',
    });
    setFormError('');
    setFormTestResult(null);
    setPasteText('');
    setParseError(null);
    setParsed(false);
    setShowForm(true);
  };

  const handleClose = () => {
    setShowForm(false);
    resetForm();
  };

  const handleSave = async () => {
    if (!formData.name || !formData.host || !formData.username) {
      setFormError('请填写名称、主机地址和用户名');
      return;
    }
    if (!editingDs && !formData.password) {
      setFormError('新建时密码为必填');
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      if (editingDs) {
        const updateData: Record<string, unknown> = {
          name: formData.name, db_type: formData.db_type, host: formData.host,
          port: formData.port, database_name: formData.database_name, username: formData.username,
          description: formData.description || null,
        };
        if (formData.password) updateData.password = formData.password;
        await updateDataSource(editingDs.id, updateData as Parameters<typeof updateDataSource>[1]);
      } else {
        await createDataSource(formData);
      }
      handleClose();
      fetchDatasources();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleTestDraft = async () => {
    if (!formData.host || !formData.username) {
      setFormTestResult({ success: false, message: '请填写主机和用户名' });
      return;
    }
    setFormTesting(true);
    setFormTestResult(null);
    try {
      if (editingDs && !formData.password) {
        const result = await testDataSource(editingDs.id);
        setFormTestResult(result);
      } else {
        const result = await testDatasourceDraft({
          db_type: formData.db_type,
          host: formData.host,
          port: formData.port,
          database_name: formData.database_name || undefined,
          username: formData.username,
          password: formData.password,
        });
        setFormTestResult(result);
      }
    } catch {
      setFormTestResult({ success: false, message: '测试请求失败' });
    } finally {
      setFormTesting(false);
    }
  };

  const handleParse = async () => {
    if (!pasteText.trim()) return;
    setParsing(true);
    setParseError(null);
    try {
      const data = await parseDatasourceConfig(pasteText);
      if (data.error) {
        setParseError(data.error);
        return;
      }
      setFormData(prev => ({
        ...prev,
        name: data.name || prev.name,
        db_type: data.db_type || prev.db_type,
        host: data.host || prev.host,
        port: data.port || prev.port,
        database_name: data.database_name || prev.database_name,
        username: data.username || prev.username,
        password: data.password || prev.password,
      }));
      setParsed(true);
    } catch {
      setParseError('解析请求失败，请检查网络');
    } finally {
      setParsing(false);
    }
  };

  const handleTest = async (id: number) => {
    setTestingId(id);
    try {
      const result = await testDataSource(id);
      setModalNotify(result);
    } catch {
      setModalNotify({ success: false, message: '测试请求失败' });
    } finally {
      setTestingId(null);
      fetchDatasources();
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteDataSource(id);
      setModalNotify({ success: true, message: '数据源已删除' });
      fetchDatasources();
    } catch (e: unknown) {
      setModalNotify({ success: false, message: e instanceof Error ? e.message : '删除失败' });
    }
  };

  const formatDate = (s: string) => s ? s.replace('T', ' ').slice(0, 16) : '-';

  // ======================== FORM VIEW ========================
  if (showForm) {
    return (
      <div className="min-h-screen bg-slate-50">
        {/* Header */}
        <div className="bg-white border-b border-slate-200 px-8 py-5">
          <div className="max-w-4xl mx-auto flex items-center gap-3">
            <button onClick={handleClose} className="text-slate-400 hover:text-slate-700 transition-colors">
              <i className="ri-arrow-left-line text-xl" />
            </button>
            <div>
              <h1 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
                <i className="ri-database-2-line text-blue-500" />
                {editingDs ? '编辑数据源' : '新建数据源'}
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">填写完成后点击右下角「保存」，或点击左侧箭头返回列表</p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="max-w-4xl mx-auto px-8 py-7">
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">

            {/* AI Parse Section (only for new) */}
            {!editingDs && (
              <div className="px-6 py-5 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-slate-100">
                <div className="flex items-center gap-2 mb-2">
                  <i className="ri-sparkling-line text-blue-500" />
                  <span className="text-sm font-medium text-slate-700">粘贴配置 / AI 解析</span>
                  <span className="text-xs text-slate-400">支持 JSON、.env、JDBC URL、自然语言描述</span>
                </div>
                <textarea
                  value={pasteText}
                  onChange={e => { setPasteText(e.target.value); setParsed(false); setParseError(null); }}
                  className="w-full px-3 py-2.5 border border-slate-200 rounded-lg text-sm font-mono resize-none bg-white focus:outline-none focus:border-blue-400"
                  rows={3}
                  placeholder={'host=rm-xxx.rds.aliyuncs.com port=3306 user=bi_zy password=xxx db=bidm\n或粘贴 JSON / JDBC URL / .env 格式'}
                />
                <div className="flex items-center gap-3 mt-2">
                  <button
                    onClick={handleParse}
                    disabled={parsing || !pasteText.trim()}
                    className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5"
                  >
                    {parsing ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-sparkling-line" />}
                    AI 解析
                  </button>
                  {parsed && <span className="text-xs text-green-600 flex items-center gap-1"><i className="ri-check-line" />解析成功，请确认后保存</span>}
                  {parseError && <span className="text-xs text-red-500">{parseError}</span>}
                </div>
              </div>
            )}

            {/* Form Fields */}
            <div className="px-6 py-6 space-y-5">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">数据库类型 <span className="text-red-500">*</span></label>
                  <select
                    value={formData.db_type}
                    onChange={e => {
                      const t = e.target.value;
                      const port = DB_TYPE_PORT_DEFAULTS[t] || formData.port;
                      setFormData({ ...formData, db_type: t, port });
                    }}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 bg-white"
                  >
                    {DB_TYPE_OPTIONS.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">名称 <span className="text-red-500">*</span></label>
                  <input type="text" value={formData.name}
                    onChange={e => setFormData({ ...formData, name: e.target.value })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                    placeholder="如: 生产-阿里云-MySQL" />
                </div>
              </div>

              <div className="grid grid-cols-4 gap-4">
                <div className="col-span-3">
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">主机地址 <span className="text-red-500">*</span></label>
                  <input type="text" value={formData.host}
                    onChange={e => setFormData({ ...formData, host: e.target.value })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                    placeholder="rm-xxx.mysql.rds.aliyuncs.com" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">端口 <span className="text-red-500">*</span></label>
                  <input type="number" value={formData.port}
                    onChange={e => setFormData({ ...formData, port: Number(e.target.value) })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">数据库名</label>
                <input type="text" value={formData.database_name}
                  onChange={e => setFormData({ ...formData, database_name: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="选填，留空则连接服务器级别" />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">用户名 <span className="text-red-500">*</span></label>
                  <input type="text" value={formData.username}
                    onChange={e => setFormData({ ...formData, username: e.target.value })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                    placeholder="bi_zy" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">密码 {!editingDs && <span className="text-red-500">*</span>}</label>
                  <input type="password" value={formData.password}
                    onChange={e => setFormData({ ...formData, password: e.target.value })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                    placeholder={editingDs ? '留空则保持不变' : '输入密码'} />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">备注</label>
                <textarea value={formData.description}
                  onChange={e => setFormData({ ...formData, description: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 resize-none"
                  rows={2}
                  placeholder="选填，描述该连接的用途，如：生产环境 OpenClaw 主库" />
              </div>

              {formError && (
                <div className="text-sm text-red-600 bg-red-50 px-4 py-2.5 rounded-lg">{formError}</div>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-slate-100 flex items-center justify-between bg-slate-50">
              <div className="flex items-center gap-3">
                <button
                  onClick={handleTestDraft}
                  disabled={formTesting}
                  className="px-4 py-2 text-sm border border-slate-300 rounded-lg text-slate-600 hover:bg-white disabled:opacity-50 flex items-center gap-1.5"
                >
                  {formTesting ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-link" />}
                  测试连接
                </button>
                {formTestResult && (
                  <span className={`text-xs flex items-center gap-1 ${formTestResult.success ? 'text-green-600' : 'text-red-500'}`}>
                    <i className={formTestResult.success ? 'ri-check-line' : 'ri-close-line'} />
                    {formTestResult.message}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <button onClick={handleClose}
                  className="px-4 py-2 text-sm border border-slate-300 rounded-lg text-slate-600 hover:bg-white">
                  取消
                </button>
                <button onClick={handleSave} disabled={saving}
                  className="px-5 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5">
                  {saving && <i className="ri-loader-4-line animate-spin" />}
                  保存
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ======================== LIST VIEW ========================
  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
              <i className="ri-database-2-line text-blue-500" />
              数据库连接管理
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">管理 MySQL、PostgreSQL、StarRocks 等数据库连接</p>
          </div>
          <button
            onClick={handleOpenNew}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 flex items-center gap-1.5"
          >
            <i className="ri-add-line" />
            新建数据源
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-7xl mx-auto px-8 py-7">
        {loading ? (
          <div className="text-center py-20 text-slate-400">
            <i className="ri-loader-2-line animate-spin text-3xl" />
            <p className="mt-2 text-sm">加载中...</p>
          </div>
        ) : loadError ? (
          <div className="text-center py-20 text-red-500">
            <i className="ri-error-warning-line text-3xl" />
            <p className="mt-2 text-sm">{loadError}</p>
          </div>
        ) : datasources.length === 0 ? (
          <div className="text-center py-20 text-slate-400">
            <i className="ri-database-2-line text-4xl opacity-40" />
            <p className="mt-3 text-sm">暂无数据源，请点击右上角「新建数据源」</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {datasources.map(ds => (
              <div key={ds.id} className="bg-white border border-slate-200 rounded-xl p-5 hover:shadow-md transition-shadow flex flex-col">
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <h3 className="font-medium text-slate-800">{ds.name}</h3>
                    <span className="text-xs text-slate-400">{DB_TYPE_OPTIONS.find(o => o.value === ds.db_type)?.label || ds.db_type}</span>
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    {ds.last_tested_at && (
                      <span className={`text-xs px-2 py-0.5 rounded-full flex items-center gap-1 ${ds.last_test_success ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'}`}>
                        <i className={ds.last_test_success ? 'ri-check-line' : 'ri-close-line'} />
                        {ds.last_test_success ? '连通' : '断连'}
                      </span>
                    )}
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full ${ds.is_active ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-500'}`}
                    >
                      {ds.is_active ? '已启用' : '已停用'}
                    </span>
                  </div>
                </div>
                <div className="text-xs text-slate-500 space-y-1 mb-4 flex-1">
                  <div className="truncate" title={`${ds.host}:${ds.port}`}><span className="text-slate-400">主机：</span>{ds.host}:{ds.port}</div>
                  {ds.database_name && <div><span className="text-slate-400">数据库：</span>{ds.database_name}</div>}
                  <div><span className="text-slate-400">用户：</span>{ds.username}</div>
                  {ds.description && <div className="text-slate-400 italic truncate" title={ds.description}>{ds.description}</div>}
                  <div><span className="text-slate-400">创建时间：</span>{formatDate(ds.created_at)}</div>
                  <div><span className="text-slate-400">更新时间：</span>{formatDate(ds.updated_at)}</div>
                  {ds.last_tested_at && <div><span className="text-slate-400">最后测试：</span>{formatDate(ds.last_tested_at)}</div>}
                </div>
                <div className="flex items-center gap-2 pt-3 border-t border-slate-100">
                  <button onClick={() => handleTest(ds.id)}
                    disabled={testingId === ds.id}
                    className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 disabled:opacity-50 flex items-center gap-1">
                    {testingId === ds.id ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-link" />}
                    测试
                  </button>
                  <button onClick={() => handleOpenEdit(ds)}
                    className="px-3 py-1.5 text-xs border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 flex items-center gap-1">
                    <i className="ri-edit-line" /> 编辑
                  </button>
                  <button onClick={() => setConfirmModal({
                    open: true, title: '删除数据源',
                    message: `确定删除「${ds.name}」？此操作不可恢复。`,
                    onConfirm: () => { handleDelete(ds.id); setConfirmModal(null); },
                  })}
                    className="px-3 py-1.5 text-xs border border-red-200 rounded-lg text-red-500 hover:bg-red-50 flex items-center gap-1">
                    <i className="ri-delete-bin-line" /> 删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Notification */}
      {modalNotify && (
        <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center" onClick={() => setModalNotify(null)}>
          <div className="bg-white rounded-xl p-6 shadow-xl max-w-sm w-full mx-4" onClick={e => e.stopPropagation()}>
            <div className="text-center">
              <i className={`text-4xl ${modalNotify.success ? 'ri-check-line text-green-500' : 'ri-error-warning-line text-red-500'}`} />
              <p className="mt-3 text-sm text-slate-700">{modalNotify.message}</p>
              <button onClick={() => setModalNotify(null)}
                className="mt-4 px-4 py-2 text-sm bg-slate-100 rounded-lg hover:bg-slate-200 text-slate-600">
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Modal */}
      {confirmModal?.open && (
        <ConfirmModal
          open={confirmModal.open}
          title={confirmModal.title}
          message={confirmModal.message}
          onConfirm={confirmModal.onConfirm}
          onCancel={() => setConfirmModal(null)}
        />
      )}
    </div>
  );
}
