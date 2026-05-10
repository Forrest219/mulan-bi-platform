import { useState, useEffect, forwardRef, useImperativeHandle } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  listDataSources, createDataSource, updateDataSource, deleteDataSource,
  testDataSource, testDatasourceDraft, parseDatasourceConfig,
  DataSource, DB_TYPE_OPTIONS, DB_TYPE_PORT_DEFAULTS
} from '../../../api/datasources';
import { ConfirmModal } from '../../../components/ConfirmModal';

export interface DatasourcesPageRef { openNew: () => void }

const DatasourcesPage = forwardRef<DatasourcesPageRef, { headerless?: boolean }>(
function DatasourcesPage({ headerless = false }, ref) {
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // URL-driven form state
  const [searchParams, setSearchParams] = useSearchParams();
  const modeParam = searchParams.get('mode');   // 'new' | 'edit' | null
  const idParam   = searchParams.get('id');
  const showForm  = modeParam === 'new' || modeParam === 'edit';
  const editingDs = idParam ? datasources.find(d => String(d.id) === idParam) ?? null : null;
  const [formData, setFormData] = useState({
    name: '', db_type: 'mysql', host: '', port: 3306,
    database_name: '', username: '', password: '', description: '',
  });
  const [passwordMode, setPasswordMode] = useState<'saved' | 'replace'>('replace');
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  // Test in form
  const [formTesting, setFormTesting] = useState(false);
  const [formTestResult, setFormTestResult] = useState<{ success: boolean; message: string } | null>(null);

  // List actions
  const [testingId, setTestingId] = useState<number | null>(null);
  const [modalNotify, setModalNotify] = useState<{ success: boolean; message: string } | null>(null);
  const [copyToast, setCopyToast] = useState<string | null>(null);

  const handleCopyHost = (host: string, port: number) => {
    const text = `${host}:${port}`;
    navigator.clipboard.writeText(text).then(() => {
      setCopyToast(`已复制 ${text}`);
      setTimeout(() => setCopyToast(null), 2000);
    }).catch(() => {
      setCopyToast('复制失败，请手动复制');
      setTimeout(() => setCopyToast(null), 2000);
    });
  };
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

  // Populate / reset form when URL mode changes
  useEffect(() => {
    if (modeParam === 'new') {
      setFormData({ name: '', db_type: 'mysql', host: '', port: 3306, database_name: '', username: '', password: '', description: '' });
      setFormError('');
      setFormTestResult(null);
      setFormTesting(false);
      setPasswordMode('replace');
      setPasteText('');
      setParseError(null);
      setParsed(false);
    } else if (modeParam === 'edit' && editingDs) {
      setFormData({
        name: editingDs.name, db_type: editingDs.db_type, host: editingDs.host,
        port: editingDs.port, database_name: editingDs.database_name,
        username: editingDs.username, password: '',
        description: editingDs.description ?? '',
      });
      setPasswordMode(editingDs.has_password ? 'saved' : 'replace');
      setFormError('');
      setFormTestResult(null);
      setPasteText('');
      setParseError(null);
      setParsed(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modeParam, editingDs?.id]);

  const handleOpenNew = () => {
    setSearchParams(prev => { const n = new URLSearchParams(prev); n.set('mode', 'new'); n.delete('id'); return n; });
  };

  useImperativeHandle(ref, () => ({ openNew: handleOpenNew }));

  const handleOpenEdit = (ds: DataSource) => {
    setSearchParams(prev => { const n = new URLSearchParams(prev); n.set('mode', 'edit'); n.set('id', String(ds.id)); return n; });
  };

  const handleClose = () => {
    setSearchParams(prev => { const n = new URLSearchParams(prev); n.delete('mode'); n.delete('id'); return n; });
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
    if (!formData.password && (!editingDs || !editingDs.has_password)) {
      setFormTestResult({ success: false, message: '请先输入密码' });
      return;
    }
    setFormTesting(true);
    setFormTestResult(null);
    try {
      const result = await testDatasourceDraft({
        datasource_id: editingDs?.id,
        db_type: formData.db_type,
        host: formData.host,
        port: formData.port,
        database_name: formData.database_name || undefined,
        username: formData.username,
        password: formData.password || undefined,
      });
      setFormTestResult(result);
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
    const dbLabel = DB_TYPE_OPTIONS.find(o => o.value === formData.db_type)?.label || formData.db_type;
    const hasSavedPassword = Boolean(editingDs?.has_password);
    const testUsesSavedPassword = Boolean(editingDs && !formData.password && hasSavedPassword);
    const lastTestLabel = editingDs?.last_tested_at
      ? `${editingDs.last_test_success ? '上次测试成功' : '上次测试失败'} · ${formatDate(editingDs.last_tested_at)}`
      : '尚未测试';

    return (
      <div className="min-h-screen bg-slate-50">
        {/* Header */}
        <div className="bg-white border-b border-slate-200 px-8 py-5">
          <div className="max-w-5xl mx-auto flex items-start gap-4">
            <button
              onClick={handleClose}
              className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-800 transition-colors"
              aria-label="返回"
            >
              <i className="ri-arrow-left-line text-lg" />
            </button>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="min-w-0 truncate text-xl font-semibold text-slate-900">
                  {editingDs ? formData.name || editingDs.name : '新建数据库连接'}
                </h1>
                <span className="rounded-md border border-blue-100 bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                  {dbLabel}
                </span>
                {editingDs && (
                  <span className={`rounded-md border px-2 py-0.5 text-xs font-medium ${
                    editingDs.last_test_success
                      ? 'border-emerald-100 bg-emerald-50 text-emerald-700'
                      : 'border-slate-200 bg-slate-50 text-slate-500'
                  }`}>
                    {lastTestLabel}
                  </span>
                )}
              </div>
              <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                <span>{formData.host || '未填写主机'}:{formData.port || '-'}</span>
                <span>{formData.username || '未填写用户'}</span>
                <span>{formData.database_name || '服务器级连接'}</span>
              </p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="max-w-5xl mx-auto px-8 py-7">
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">

            {/* AI Parse Section (only for new) */}
            {!editingDs && (
              <div className="px-7 py-5 bg-blue-50/70 border-b border-blue-100">
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
            <div className="px-7 py-7 space-y-8">
              <section className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-slate-800">连接信息</h2>
                  {formData.db_type === 'starrocks' && (
                    <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">MySQL 协议</span>
                  )}
                </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">数据库类型 <span className="text-red-500">*</span></label>
                  <select
                    value={formData.db_type}
                    onChange={e => {
                      const t = e.target.value;
                      const port = DB_TYPE_PORT_DEFAULTS[t] || formData.port;
                      setFormData({ ...formData, db_type: t, port });
                      setFormTestResult(null);
                    }}
                    className="h-11 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
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
                    className="h-11 w-full rounded-lg border border-slate-200 px-4 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                    placeholder="如: 生产-阿里云-MySQL" />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
                <div className="md:col-span-3">
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">主机地址 <span className="text-red-500">*</span></label>
                  <input type="text" value={formData.host}
                    onChange={e => { setFormData({ ...formData, host: e.target.value }); setFormTestResult(null); }}
                    className="h-11 w-full rounded-lg border border-slate-200 px-4 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                    placeholder="rm-xxx.mysql.rds.aliyuncs.com" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">端口 <span className="text-red-500">*</span></label>
                  <input type="number" value={formData.port}
                    onChange={e => { setFormData({ ...formData, port: Number(e.target.value) }); setFormTestResult(null); }}
                    className="h-11 w-full rounded-lg border border-slate-200 px-4 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">数据库名</label>
                <input type="text" value={formData.database_name}
                  onChange={e => { setFormData({ ...formData, database_name: e.target.value }); setFormTestResult(null); }}
                  className="h-11 w-full rounded-lg border border-slate-200 px-4 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  placeholder="选填，留空则连接服务器级别" />
              </div>
              </section>

              <section className="space-y-4 border-t border-slate-100 pt-6">
                <h2 className="text-sm font-semibold text-slate-800">认证信息</h2>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">用户名 <span className="text-red-500">*</span></label>
                  <input type="text" value={formData.username}
                    onChange={e => { setFormData({ ...formData, username: e.target.value }); setFormTestResult(null); }}
                    className="h-11 w-full rounded-lg border border-slate-200 px-4 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                    placeholder="bi_zy" />
                </div>
                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <label className="block text-sm font-medium text-slate-600">密码 {!editingDs && <span className="text-red-500">*</span>}</label>
                    {editingDs && hasSavedPassword && passwordMode === 'saved' && (
                      <button
                        type="button"
                        onClick={() => { setPasswordMode('replace'); setFormData({ ...formData, password: '' }); setFormTestResult(null); }}
                        className="text-xs font-medium text-blue-600 hover:text-blue-700"
                      >
                        更换密码
                      </button>
                    )}
                    {editingDs && hasSavedPassword && passwordMode === 'replace' && (
                      <button
                        type="button"
                        onClick={() => { setPasswordMode('saved'); setFormData({ ...formData, password: '' }); setFormTestResult(null); }}
                        className="text-xs font-medium text-slate-500 hover:text-slate-700"
                      >
                        使用已保存密码
                      </button>
                    )}
                  </div>
                  {editingDs && hasSavedPassword && passwordMode === 'saved' ? (
                    <div className="flex h-11 items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-3">
                      <div className="flex items-center gap-2 text-sm font-medium text-emerald-800">
                        <i className="ri-lock-password-line text-base" />
                        <span>已保存密码</span>
                      </div>
                      <span className="text-xs text-emerald-700">保存将继续使用原密码</span>
                    </div>
                  ) : (
                    <input type="password" value={formData.password}
                      onChange={e => { setFormData({ ...formData, password: e.target.value }); setFormTestResult(null); }}
                      className="h-11 w-full rounded-lg border border-slate-200 px-4 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                      placeholder={editingDs ? '输入新密码后将覆盖已保存密码' : '输入密码'} />
                  )}
                </div>
              </div>

              <p className="text-xs text-slate-500">
                {editingDs && hasSavedPassword
                  ? '留空保存不会修改密码；测试当前配置会在未输入新密码时复用已保存密码。'
                  : editingDs
                    ? '该连接尚未保存密码，请输入密码后测试或保存。'
                    : '创建连接时必须提供密码。'}
              </p>
              </section>

              <section className="space-y-3 border-t border-slate-100 pt-6">
                <label className="block text-sm font-medium text-slate-600 mb-1.5">备注</label>
                <textarea value={formData.description}
                  onChange={e => setFormData({ ...formData, description: e.target.value })}
                  className="w-full resize-none rounded-lg border border-slate-200 px-4 py-3 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  rows={3}
                  placeholder="选填，描述该连接的用途，如：生产环境 OpenClaw 主库" />
              </section>

              {formError && (
                <div className="text-sm text-red-600 bg-red-50 px-4 py-2.5 rounded-lg">{formError}</div>
              )}
            </div>

            {/* Footer */}
            <div className="px-7 py-5 border-t border-slate-100 flex flex-col gap-4 bg-slate-50 md:flex-row md:items-center md:justify-between">
              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={handleTestDraft}
                  disabled={formTesting || saving}
                  className="flex h-10 items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  {formTesting ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-link" />}
                  测试当前配置
                </button>
                {formTestResult && (
                  <span className={`text-xs flex items-center gap-1 ${formTestResult.success ? 'text-emerald-600' : 'text-red-500'}`}>
                    <i className={formTestResult.success ? 'ri-check-line' : 'ri-close-line'} />
                    {formTestResult.message}
                  </span>
                )}
                {!formTestResult && (
                  <span className="text-xs text-slate-500">
                    {testUsesSavedPassword ? '将使用当前表单配置和已保存密码进行测试' : '将使用当前表单配置进行测试'}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <button onClick={handleClose}
                  className="h-10 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50">
                  取消
                </button>
                <button onClick={handleSave} disabled={saving}
                  className="flex h-10 items-center gap-1.5 rounded-lg bg-blue-600 px-5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
                  {saving && <i className="ri-loader-4-line animate-spin" />}
                  {editingDs ? '保存更改' : '创建连接'}
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
      {/* Header — only when used as standalone page */}
      {!headerless && (
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
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors"
          >
            <i className="ri-add-line" />
            新建数据源
          </button>
        </div>
      </div>
      )}

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
                      <span className={`text-xs px-2 py-0.5 rounded-full flex items-center gap-1 border ${
                        ds.last_test_success
                          ? 'bg-emerald-50 text-emerald-600 border-emerald-200'
                          : 'bg-red-50 text-red-600 border-red-200'
                      }`}>
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
                  <div className="flex items-center gap-1" title={`${ds.host}:${ds.port}`}>
                    <span className="text-slate-400 flex-shrink-0">主机：</span>
                    <span className="truncate">{ds.host}:{ds.port}</span>
                    <button
                      onClick={e => { e.stopPropagation(); handleCopyHost(ds.host, ds.port); }}
                      className="flex-shrink-0 text-slate-300 hover:text-slate-600 transition-colors"
                      title="复制主机地址"
                    >
                      <i className="ri-file-copy-line text-[11px]" />
                    </button>
                  </div>
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

      {/* Copy Toast */}
      {copyToast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-slate-800 text-white text-xs px-4 py-2 rounded-lg shadow-lg flex items-center gap-2 pointer-events-none">
          <i className="ri-check-line text-emerald-400" />
          {copyToast}
        </div>
      )}

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
});

export default DatasourcesPage;
