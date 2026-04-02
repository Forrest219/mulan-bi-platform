import { useState, useEffect } from 'react';
import {
  listDataSources, createDataSource, updateDataSource,
  deleteDataSource, testDataSource, DataSource,
  DB_TYPE_OPTIONS, DB_TYPE_PORT_DEFAULTS,
} from '../../../api/datasources';
import { ConfirmModal } from '../../../components/ConfirmModal';

export default function AdminDatasourcesPage() {
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingDs, setEditingDs] = useState<DataSource | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    db_type: 'mysql',
    host: '',
    port: 3306,
    database_name: '',
    username: '',
    password: '',
  });
  const [formError, setFormError] = useState('');
  const [testingId, setTestingId] = useState<number | null>(null);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean; title: string; message: string; onConfirm: () => void;
  } | null>(null);

  const fetchDataSources = async () => {
    try {
      const data = await listDataSources();
      setDataSources(data.datasources);
    } catch (e: any) {
      setLoadError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDataSources(); }, []);

  const resetForm = () => {
    setFormData({ name: '', db_type: 'mysql', host: '', port: 3306, database_name: '', username: '', password: '' });
    setFormError('');
  };

  const openCreate = () => {
    resetForm();
    setEditingDs(null);
    setShowModal(true);
  };

  const openEdit = (ds: DataSource) => {
    setEditingDs(ds);
    setFormData({
      name: ds.name,
      db_type: ds.db_type,
      host: ds.host,
      port: ds.port,
      database_name: ds.database_name,
      username: ds.username,
      password: '',
    });
    setFormError('');
    setShowModal(true);
  };

  const handleDbTypeChange = (db_type: string) => {
    setFormData({ ...formData, db_type, port: DB_TYPE_PORT_DEFAULTS[db_type] || 3306 });
  };

  const handleSave = async () => {
    if (!formData.name || !formData.host || !formData.database_name || !formData.username) {
      setFormError('请填写所有必填字段');
      return;
    }
    if (!formData.password && !editingDs) {
      setFormError('新建数据源必须填写密码');
      return;
    }
    try {
      if (editingDs) {
        const updateData: Record<string, unknown> = {
          name: formData.name,
          db_type: formData.db_type,
          host: formData.host,
          port: formData.port,
          database_name: formData.database_name,
          username: formData.username,
        };
        if (formData.password) updateData.password = formData.password;
        await updateDataSource(editingDs.id, updateData as Parameters<typeof updateDataSource>[1]);
      } else {
        await createDataSource(formData as Parameters<typeof createDataSource>[0]);
      }
      setShowModal(false);
      resetForm();
      fetchDataSources();
    } catch (e: any) {
      setFormError(e.message);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteDataSource(id);
      setConfirmModal(null);
      fetchDataSources();
    } catch (e: any) {
      setConfirmModal(null);
      setLoadError(e.message);
    }
  };

  const handleTest = async (id: number) => {
    setTestingId(id);
    setTestResult(null);
    try {
      const result = await testDataSource(id);
      setTestResult(result);
    } catch (e: any) {
      setTestResult({ success: false, message: e.message });
    } finally {
      setTestingId(null);
    }
  };

  const dbTypeLabel = (type: string) => DB_TYPE_OPTIONS.find((o) => o.value === type)?.label || type;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Page header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="w-5 h-5 flex items-center justify-center">
                <i className="ri-database-2-line text-slate-500 text-base" />
              </span>
              <h1 className="text-lg font-semibold text-slate-800">数据源管理</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-7">数据库连接配置 · 用于数据仓库体检与质量监控</p>
          </div>
          <button
            onClick={openCreate}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[12px] font-medium rounded-lg hover:bg-slate-700 transition-colors cursor-pointer"
          >
            <i className="ri-add-line" />
            添加数据源
          </button>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-7">
        {loadError && (
          <div className="mb-4 px-4 py-3 bg-red-50 text-red-700 border border-red-200 rounded-lg text-sm">{loadError}</div>
        )}

        {testResult && (
          <div className={`mb-4 px-4 py-3 border rounded-lg text-sm ${testResult.success ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
            <i className={`mr-1 ${testResult.success ? 'ri-checkbox-circle-line' : 'ri-error-warning-line'}`} />
            {testResult.message}
            <button onClick={() => setTestResult(null)} className="ml-3 text-slate-400 hover:text-slate-600">×</button>
          </div>
        )}

        {loading ? (
          <div className="text-center py-20 text-slate-400">加载中...</div>
        ) : dataSources.length === 0 ? (
          <div className="text-center py-20">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-slate-100 flex items-center justify-center">
              <i className="ri-database-line text-2xl text-slate-400" />
            </div>
            <p className="text-slate-500 mb-4">暂无数据源，请添加</p>
            <button onClick={openCreate} className="px-4 py-2 bg-slate-900 text-white text-sm rounded-lg hover:bg-slate-700 cursor-pointer">
              添加数据源
            </button>
          </div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50">
                  {['名称', '类型', '连接地址', '数据库', '用户名', '状态', '操作'].map((h) => (
                    <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-3 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dataSources.map((ds) => (
                  <tr key={ds.id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3 text-[13px] font-semibold text-slate-700">{ds.name}</td>
                    <td className="px-4 py-3">
                      <span className="text-[11px] font-medium px-2 py-0.5 bg-slate-100 text-slate-600 rounded">
                        {dbTypeLabel(ds.db_type)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-slate-600 font-mono">{ds.host}:{ds.port}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-600 font-mono">{ds.database_name}</td>
                    <td className="px-4 py-3 text-[12px] text-slate-500">{ds.username}</td>
                    <td className="px-4 py-3">
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${ds.is_active ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-400'}`}>
                        {ds.is_active ? '活跃' : '停用'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleTest(ds.id)}
                          disabled={testingId === ds.id}
                          className="text-[11px] px-2 py-1 text-slate-500 hover:text-blue-600 border border-slate-200 rounded hover:border-blue-300 transition-colors cursor-pointer disabled:opacity-50"
                        >
                          {testingId === ds.id ? '测试中...' : '测试连接'}
                        </button>
                        <button
                          onClick={() => openEdit(ds)}
                          className="text-[11px] px-2 py-1 text-slate-500 hover:text-slate-800 cursor-pointer"
                        >
                          编辑
                        </button>
                        <button
                          onClick={() => setConfirmModal({
                            open: true,
                            title: '删除数据源',
                            message: `确定删除数据源「${ds.name}」？删除后不可恢复。`,
                            onConfirm: () => handleDelete(ds.id),
                          })}
                          className="text-[11px] px-2 py-1 text-red-400 hover:text-red-600 cursor-pointer"
                        >
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold text-slate-800">
                {editingDs ? '编辑数据源' : '添加数据源'}
              </h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-slate-600 cursor-pointer">
                <i className="ri-close-line text-lg" />
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              {formError && (
                <div className="px-3 py-2 bg-red-50 text-red-600 text-xs rounded border border-red-200">{formError}</div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">名称 <span className="text-red-500">*</span></label>
                  <input
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="e.g. 生产 MySQL"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">数据库类型 <span className="text-red-500">*</span></label>
                  <select
                    value={formData.db_type}
                    onChange={(e) => handleDbTypeChange(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400 bg-white"
                  >
                    {DB_TYPE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2">
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">主机地址 <span className="text-red-500">*</span></label>
                  <input
                    value={formData.host}
                    onChange={(e) => setFormData({ ...formData, host: e.target.value })}
                    placeholder="e.g. 192.168.1.100"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">端口 <span className="text-red-500">*</span></label>
                  <input
                    type="number"
                    value={formData.port}
                    onChange={(e) => setFormData({ ...formData, port: Number(e.target.value) })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
              </div>
              <div>
                <label className="block text-[11px] font-medium text-slate-500 mb-1">数据库名 <span className="text-red-500">*</span></label>
                <input
                  value={formData.database_name}
                  onChange={(e) => setFormData({ ...formData, database_name: e.target.value })}
                  placeholder="e.g. analytics_db"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">用户名 <span className="text-red-500">*</span></label>
                  <input
                    value={formData.username}
                    onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-1">
                    密码 {editingDs ? '（不修改则留空）' : ''} <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="password"
                    value={formData.password}
                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    placeholder={editingDs ? '••••••••' : ''}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-[13px] focus:outline-none focus:border-slate-400"
                  />
                </div>
              </div>
            </div>
            <div className="px-6 py-4 border-t border-slate-100 flex justify-end gap-3">
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 text-[13px] text-slate-600 hover:text-slate-800 cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                className="px-4 py-2 bg-slate-900 text-white text-[13px] rounded-lg hover:bg-slate-700 cursor-pointer"
              >
                {editingDs ? '保存' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm delete */}
      {confirmModal?.open && (
        <ConfirmModal
          open={confirmModal.open}
          title={confirmModal.title}
          message={confirmModal.message}
          confirmLabel="删除"
          onConfirm={confirmModal.onConfirm}
          onCancel={() => setConfirmModal(null)}
        />
      )}
    </div>
  );
}
