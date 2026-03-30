import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  listConnections, createConnection, updateConnection, deleteConnection,
  testConnection, syncConnection, TableauConnection
} from '../../../api/tableau';

export default function TableauConnectionsPage() {
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingConn, setEditingConn] = useState<TableauConnection | null>(null);
  const [formData, setFormData] = useState({
    name: '', server_url: '', site: '', api_version: '3.21',
    token_name: '', token_value: ''
  });
  const [formError, setFormError] = useState('');
  const [testingId, setTestingId] = useState<number | null>(null);
  const [syncingId, setSyncingId] = useState<number | null>(null);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const navigate = useNavigate();

  const fetchConnections = async () => {
    try {
      const data = await listConnections();
      setConnections(data.connections);
    } catch (e: any) {
      setLoadError(e.message || '加载失败，请检查是否已登录');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchConnections(); }, []);

  const handleCreate = async () => {
    if (!formData.name || !formData.server_url || !formData.site || !formData.token_name || !formData.token_value) {
      setFormError('请填写所有必填字段');
      return;
    }
    try {
      await createConnection(formData);
      setShowModal(false);
      resetForm();
      fetchConnections();
    } catch (e: any) {
      setFormError(e.message);
    }
  };

  const handleUpdate = async () => {
    if (!editingConn) return;
    try {
      const updateData: any = { ...formData };
      if (!updateData.token_value) {
        delete updateData.token_value;
        delete updateData.token_name;
      }
      await updateConnection(editingConn.id, updateData);
      setEditingConn(null);
      resetForm();
      fetchConnections();
    } catch (e: any) {
      setFormError(e.message);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除该连接吗？')) return;
    try {
      await deleteConnection(id);
      fetchConnections();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const handleTest = async (id: number) => {
    setTestingId(id);
    setTestResult(null);
    const result = await testConnection(id);
    setTestResult(result);
    setTestingId(null);
  };

  const handleSync = async (id: number) => {
    setSyncingId(id);
    const result = await syncConnection(id);
    alert(result.message);
    setSyncingId(null);
    fetchConnections();
  };

  const openEditModal = (conn: TableauConnection) => {
    setEditingConn(conn);
    setFormData({
      name: conn.name,
      server_url: conn.server_url,
      site: conn.site,
      api_version: conn.api_version,
      token_name: conn.token_name,
      token_value: ''
    });
    setShowModal(true);
  };

  const resetForm = () => {
    setFormData({ name: '', server_url: '', site: '', api_version: '3.21', token_name: '', token_value: '' });
    setFormError('');
    setEditingConn(null);
    setTestResult(null);
  };

  const formatDate = (str: string | null) => str ? new Date(str).toLocaleString() : '-';

  if (loading) return <div className="p-8 text-center text-slate-400">加载中...</div>;
  if (loadError) return <div className="p-8 text-center text-red-500">{loadError}</div>;

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">Tableau 连接管理</h1>
          <p className="text-sm text-slate-400 mt-0.5">配置 Tableau Server 连接并同步资产</p>
        </div>
        <button onClick={() => { resetForm(); setShowModal(true); }}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 flex items-center gap-1.5">
          <i className="ri-add-line" /> 新建连接
        </button>
      </div>

      {/* Connection Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {connections.map(conn => (
          <div key={conn.id} className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h3 className="font-semibold text-slate-800">{conn.name}</h3>
                <p className="text-xs text-slate-400 mt-0.5">{conn.server_url}</p>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded-full ${conn.is_active ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>
                {conn.is_active ? '活跃' : '禁用'}
              </span>
            </div>
            <div className="space-y-1.5 text-xs text-slate-500 mb-4">
              <div><span className="text-slate-400">站点:</span> {conn.site}</div>
              <div><span className="text-slate-400">API版本:</span> {conn.api_version}</div>
              <div><span className="text-slate-400">上次同步:</span> {formatDate(conn.last_sync_at)}</div>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => handleTest(conn.id)}
                disabled={testingId === conn.id}
                className="flex-1 px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 rounded-lg flex items-center justify-center gap-1">
                {testingId === conn.id ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-plug-line" />}
                测试
              </button>
              <button onClick={() => handleSync(conn.id)}
                disabled={syncingId === conn.id}
                className="flex-1 px-3 py-1.5 text-xs bg-blue-50 hover:bg-blue-100 text-blue-600 rounded-lg flex items-center justify-center gap-1">
                {syncingId === conn.id ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-refresh-line" />}
                同步
              </button>
              <button onClick={() => navigate(`/tableau/assets?connection_id=${conn.id}`)}
                className="flex-1 px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 rounded-lg flex items-center justify-center gap-1">
                <i className="ri-folder-line" />
                资产
              </button>
            </div>
            <div className="flex items-center gap-2 mt-2">
              <button onClick={() => openEditModal(conn)}
                className="flex-1 px-3 py-1.5 text-xs text-slate-500 hover:text-slate-700">
                编辑
              </button>
              <button onClick={() => handleDelete(conn.id)}
                className="flex-1 px-3 py-1.5 text-xs text-red-500 hover:text-red-700">
                删除
              </button>
            </div>
          </div>
        ))}
        {connections.length === 0 && (
          <div className="col-span-full text-center py-12 text-slate-400">
            <i className="ri-links-line text-3xl mb-2 block" />
            暂无连接，请点击右上角创建
          </div>
        )}
      </div>

      {/* Test Result Toast */}
      {testResult && (
        <div className={`fixed bottom-6 right-6 px-4 py-3 rounded-xl shadow-lg text-sm max-w-sm z-50 ${testResult.success ? 'bg-emerald-50 border border-emerald-200 text-emerald-700' : 'bg-red-50 border border-red-200 text-red-700'}`}>
          <div className="flex items-start gap-2">
            <i className={`${testResult.success ? 'ri-check-line' : 'ri-error-warning-line'} mt-0.5`} />
            <span>{testResult.message}</span>
          </div>
        </div>
      )}

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-lg shadow-xl">
            <h2 className="text-lg font-semibold text-slate-800 mb-4">
              {editingConn ? '编辑连接' : '新建 Tableau 连接'}
            </h2>
            <div className="space-y-4">
              {formError && <div className="bg-red-50 border border-red-200 text-red-600 text-sm px-4 py-3 rounded-lg">{formError}</div>}
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">连接名称 <span className="text-red-500">*</span></label>
                <input type="text" value={formData.name}
                  onChange={e => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="如: 生产-KSYUN-MCP" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">Server URL <span className="text-red-500">*</span></label>
                <input type="text" value={formData.server_url}
                  onChange={e => setFormData({ ...formData, server_url: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="https://bi.ksyun.com" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">站点 (Site) <span className="text-red-500">*</span></label>
                  <input type="text" value={formData.site}
                    onChange={e => setFormData({ ...formData, site: e.target.value })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                    placeholder="mcp" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-1.5">API 版本</label>
                  <input type="text" value={formData.api_version}
                    onChange={e => setFormData({ ...formData, api_version: e.target.value })}
                    className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                    placeholder="3.21" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">PAT Name <span className="text-red-500">*</span></label>
                <input type="text" value={formData.token_name}
                  onChange={e => setFormData({ ...formData, token_name: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder="for_bi_team" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-1.5">
                  PAT Token <span className="text-red-500">*</span>
                  {editingConn && <span className="text-slate-400 font-normal ml-1">(留空则保持不变)</span>}
                </label>
                <input type="password" value={formData.token_value}
                  onChange={e => setFormData({ ...formData, token_value: e.target.value })}
                  className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  placeholder={editingConn ? '******' : '7fryZb09QYuahmH648nEqA==:...'} />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => { setShowModal(false); resetForm(); }}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700">取消</button>
              <button onClick={editingConn ? handleUpdate : handleCreate}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
                {editingConn ? '保存' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
