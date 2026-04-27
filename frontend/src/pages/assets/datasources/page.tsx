import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  listDataSources, createDataSource, updateDataSource, deleteDataSource,
  testDataSource, DataSource, DB_TYPE_OPTIONS, DB_TYPE_PORT_DEFAULTS
} from '../../../api/datasources';
import { ConfirmModal } from '../../../components/ConfirmModal';

export default function DatasourcesPage() {
  const navigate = useNavigate();
  const [datasources, setDatasources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingDs, setEditingDs] = useState<DataSource | null>(null);
  const [formData, setFormData] = useState({
    name: '', db_type: 'postgresql', host: '', port: 5432,
    database_name: '', username: '', password: '',
  });
  const [formError, setFormError] = useState('');
  const [testingId, setTestingId] = useState<number | null>(null);
  const [syncingId, setSyncingId] = useState<number | null>(null);
  const [modalNotify, setModalNotify] = useState<{ success: boolean; message: string } | null>(null);
  const [confirmModal, setConfirmModal] = useState<{ open: boolean; title: string; message: string; onConfirm: () => void } | null>(null);

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

  const handleCreate = async () => {
    if (!formData.name || !formData.host || !formData.database_name || !formData.username || !formData.password) {
      setFormError('请填写所有必填字段');
      return;
    }
    try {
      await createDataSource(formData);
      setShowModal(false);
      resetForm();
      fetchDatasources();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : '创建失败');
    }
  };

  const handleUpdate = async () => {
    if (!editingDs) return;
    try {
      const updateData: Record<string, unknown> = {
        name: formData.name, db_type: formData.db_type, host: formData.host,
        port: formData.port, database_name: formData.database_name, username: formData.username,
      };
      if (formData.password) updateData.password = formData.password;
      await updateDataSource(editingDs.id, updateData as Parameters<typeof updateDataSource>[1]);
      setShowModal(false);
      resetForm();
      fetchDatasources();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : '更新失败');
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

  const handleTest = async (id: number) => {
    setTestingId(id);
    const result = await testDataSource(id);
    setModalNotify(result);
    setTestingId(null);
    fetchDatasources();
  };

  const openEditModal = (ds: DataSource) => {
    setEditingDs(ds);
    setFormData({
      name: ds.name, db_type: ds.db_type, host: ds.host, port: ds.port,
      database_name: ds.database_name, username: ds.username, password: '',
    });
    setShowModal(true);
  };

  const resetForm = () => {
    setFormData({ name: '', db_type: 'postgresql', host: '', port: 5432, database_name: '', username: '', password: '' });
    setFormError('');
    setEditingDs(null);
    setModalNotify(null);
  };

  const formatDate = (str: string) => new Date(str).toLocaleString();

  const getDbTypeLabel = (t: string) => DB_TYPE_OPTIONS.find(o => o.value === t)?.label ?? t;

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;
  if (loadError) return <div className="p-8 text-center text-red-500">{loadError}</div>;

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">数据源管理</h1>
          <p className="text-sm text-slate-400 mt-0.5">管理数据库连接与数据源配置</p>
        </div>
        <button onClick={() => { resetForm(); setShowModal(true); }}
          className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800 flex items-center gap-1.5">
          <i className="ri-add-line" /> 新建数据源
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {datasources.map(ds => (
          <div key={ds.id} className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h3 className="font-semibold text-slate-800">{ds.name}</h3>
                <p className="text-xs text-slate-400 mt-0.5">{getDbTypeLabel(ds.db_type)}</p>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded-full ${ds.is_active ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>
                {ds.is_active ? '启用' : '禁用'}
              </span>
            </div>
            <div className="space-y-1.5 text-xs text-slate-500 mb-4">
              <div><span className="text-slate-400">地址：</span> {ds.host}:{ds.port}/{ds.database_name}</div>
              <div><span className="text-slate-400">用户：</span> {ds.username}</div>
              <div><span className="text-slate-400">更新时间：</span> {formatDate(ds.updated_at)}</div>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => handleTest(ds.id)}
                disabled={testingId === ds.id}
                className="flex-1 px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 rounded-lg flex items-center justify-center gap-1">
                {testingId === ds.id ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-plug-line" />}
                测试
              </button>
              <button onClick={() => openEditModal(ds)}
                className="flex-1 px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 rounded-lg flex items-center justify-center gap-1">
                <i className="ri-edit-line" /> 编辑
              </button>
              <button onClick={() => {
                setConfirmModal({
                  open: true, title: '删除数据源',
                  message: `确定要删除数据源 "${ds.name}" 吗？`,
                  onConfirm: () => { setConfirmModal(null); handleDelete(ds.id); },
                });
              }}
                className="flex-1 px-3 py-1.5 text-xs text-red-500 hover:text-red-700">
                删除
              </button>
            </div>
          </div>
        ))}
        {datasources.length === 0 && (
          <div className="col-span-full text-center py-12 text-slate-400">
            <i className="ri-database-2-line text-3xl mb-2 block" />
            暂无数据源，请点击右上角创建
          </div>
        )}
      </div>

      {modalNotify && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setModalNotify(null)}>
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

      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-lg shadow-xl max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-slate-800 mb-4">
              {editingDs ? '编辑数据源' : '新建数据源'}
            </h2>
            <div className="space-y-4">
              {formError && <div className="bg-red-50 border border-red-200 text-red-600 text-sm px-4 py-3 rounded-lg">{formError}</div>}
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">数据库类型</label>
                <select value={formData.db_type}
                  onChange={e => setFormData({ ...formData, db_type: e.target.value, port: DB_TYPE_PORT_DEFAULTS[e.target.value] || 5432 })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 bg-white">
                  {DB_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">名称 <span className="text-red-500">*</span></label>
                <input type="text" value={formData.name}
                  onChange={e => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="如: 生产-KSYUN-DB" />
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">主机地址 <span className="text-red-500">*</span></label>
                  <input type="text" value={formData.host}
                    onChange={e => setFormData({ ...formData, host: e.target.value })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                    placeholder="rm-xxx.ksyun.com" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">端口 <span className="text-red-500">*</span></label>
                  <input type="number" value={formData.port}
                    onChange={e => setFormData({ ...formData, port: Number(e.target.value) })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">数据库名 <span className="text-red-500">*</span></label>
                <input type="text" value={formData.database_name}
                  onChange={e => setFormData({ ...formData, database_name: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="bi_warehouse" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">用户名 <span className="text-red-500">*</span></label>
                <input type="text" value={formData.username}
                  onChange={e => setFormData({ ...formData, username: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="root" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">
                  密码 <span className="text-red-500">*</span>
                  {editingDs && <span className="text-slate-400 font-normal ml-1">(留空则保持不变)</span>}
                </label>
                <input type="password" value={formData.password}
                  onChange={e => setFormData({ ...formData, password: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder={editingDs ? '******' : '请输入密码'} />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => { setShowModal(false); resetForm(); }}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700">取消</button>
              <button onClick={editingDs ? handleUpdate : handleCreate}
                className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800">
                {editingDs ? '保存' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmModal && (
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
