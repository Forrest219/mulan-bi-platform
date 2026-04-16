/**
 * LLMConfigsPage — /system/llm-configs
 *
 * admin-only LLM 多配置管理页。
 *
 * 功能：
 * - 列表展示所有 LLM 配置（purpose、display_name、provider、model、is_active、priority）
 * - 新增 / 编辑表单
 * - 删除按钮（ConfirmModal）
 * - 仅 admin 可见
 *
 * 后端 API：
 *   GET    /api/llm/configs         → LLMConfigItem[]
 *   POST   /api/llm/configs         → LLMConfigItem
 *   PUT    /api/llm/configs/:id     → LLMConfigItem
 *   DELETE /api/llm/configs/:id     → 204
 */
import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../../context/AuthContext';
import { ConfirmModal } from '../../../components/ConfirmModal';

// ─── Types ────────────────────────────────────────────────────────────────────

interface LLMConfigItem {
  id: number;
  purpose: string;
  display_name: string;
  provider: 'openai' | 'anthropic' | string;
  model: string;
  base_url: string;
  temperature: number;
  max_tokens: number;
  is_active: boolean;
  priority: number;
  has_api_key?: boolean;
  created_at: string;
  updated_at: string;
}

interface LLMConfigForm {
  purpose: string;
  display_name: string;
  provider: string;
  model: string;
  base_url: string;
  api_key: string;
  temperature: number;
  max_tokens: number;
  is_active: boolean;
  priority: number;
}

const defaultForm: LLMConfigForm = {
  purpose: 'general',
  display_name: '',
  provider: 'openai',
  model: 'gpt-4o-mini',
  base_url: 'https://api.openai.com/v1',
  api_key: '',
  temperature: 0.7,
  max_tokens: 1024,
  is_active: true,
  priority: 0,
};

// ─── API helpers ──────────────────────────────────────────────────────────────

async function apiListConfigs(): Promise<LLMConfigItem[]> {
  const res = await fetch('/api/llm/configs', { credentials: 'include' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function apiCreateConfig(data: LLMConfigForm): Promise<LLMConfigItem> {
  const res = await fetch('/api/llm/configs', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiUpdateConfig(id: number, data: Partial<LLMConfigForm>): Promise<LLMConfigItem> {
  const res = await fetch(`/api/llm/configs/${id}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiDeleteConfig(id: number): Promise<void> {
  const res = await fetch(`/api/llm/configs/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok && res.status !== 204) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
}

// ─── LLMConfigsPage ──────────────────────────────────────────────────────────

export default function LLMConfigsPage() {
  const { isAdmin } = useAuth();

  const [configs, setConfigs] = useState<LLMConfigItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 表单相关
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<LLMConfigForm>(defaultForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [showApiKey, setShowApiKey] = useState(false);

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<LLMConfigItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadConfigs = useCallback(() => {
    setLoading(true);
    setError(null);
    apiListConfigs()
      .then(setConfigs)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  // 仅 admin 可见
  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <i className="ri-lock-line text-5xl text-slate-300 mb-4 block" />
          <h2 className="text-xl font-semibold text-slate-700 mb-2">无权限访问</h2>
          <p className="text-slate-500">仅管理员可管理 LLM 配置</p>
        </div>
      </div>
    );
  }

  const handleOpenNew = () => {
    setEditingId(null);
    setForm(defaultForm);
    setFormError(null);
    setShowApiKey(false);
    setShowForm(true);
  };

  const handleOpenEdit = (cfg: LLMConfigItem) => {
    setEditingId(cfg.id);
    setForm({
      purpose: cfg.purpose,
      display_name: cfg.display_name,
      provider: cfg.provider,
      model: cfg.model,
      base_url: cfg.base_url,
      api_key: '', // 编辑时 api_key 留空，不更新
      temperature: cfg.temperature,
      max_tokens: cfg.max_tokens,
      is_active: cfg.is_active,
      priority: cfg.priority,
    });
    setFormError(null);
    setShowApiKey(false);
    setShowForm(true);
  };

  const handleSave = async () => {
    setFormError(null);
    setSaving(true);
    try {
      if (editingId !== null) {
        // 编辑：api_key 留空不更新
        const payload: Partial<LLMConfigForm> = { ...form };
        if (!payload.api_key) delete payload.api_key;
        await apiUpdateConfig(editingId, payload);
      } else {
        await apiCreateConfig(form);
      }
      setShowForm(false);
      loadConfigs();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await apiDeleteConfig(deleteTarget.id);
      setDeleteTarget(null);
      loadConfigs();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  };

  const providerLabel = (p: string) => ({ openai: 'OpenAI', anthropic: 'Anthropic' }[p] ?? p);

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <i className="ri-robot-2-line text-slate-500 text-base" />
              <h1 className="text-lg font-semibold text-slate-800">LLM 多配置管理</h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-6">
              管理不同用途的 LLM Provider 配置（多配置支持按 purpose 选择）
            </p>
          </div>
          <button
            onClick={handleOpenNew}
            className="flex items-center gap-1.5 px-4 py-2 bg-slate-900 text-white text-sm
                       rounded-lg hover:bg-slate-800 transition-colors"
          >
            <i className="ri-add-line" />
            新增配置
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-5xl mx-auto px-8 py-7">
        {/* 错误提示 */}
        {error && (
          <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg flex items-center gap-2">
            <i className="ri-error-warning-line" />
            {error}
          </div>
        )}

        {/* 加载态 */}
        {loading && (
          <div className="flex items-center justify-center py-16">
            <div className="flex items-center gap-2 text-slate-400">
              <span className="w-5 h-5 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
              加载中...
            </div>
          </div>
        )}

        {/* 空态 */}
        {!loading && configs.length === 0 && (
          <div className="text-center py-16">
            <i className="ri-robot-line text-5xl text-slate-200 mb-4 block" />
            <p className="text-slate-500 mb-4">暂无 LLM 配置</p>
            <button
              onClick={handleOpenNew}
              className="px-4 py-2 bg-slate-900 text-white text-sm rounded-lg hover:bg-slate-800 transition-colors"
            >
              添加第一个配置
            </button>
          </div>
        )}

        {/* 配置列表 */}
        {!loading && configs.length > 0 && (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-4 py-3 text-left font-medium text-slate-600">用途</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">名称</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Provider</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Model</th>
                  <th className="px-4 py-3 text-center font-medium text-slate-600">优先级</th>
                  <th className="px-4 py-3 text-center font-medium text-slate-600">状态</th>
                  <th className="px-4 py-3 text-right font-medium text-slate-600">操作</th>
                </tr>
              </thead>
              <tbody>
                {configs.map((cfg) => (
                  <tr key={cfg.id} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded-md font-mono">
                        {cfg.purpose}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-700 font-medium">{cfg.display_name || '-'}</td>
                    <td className="px-4 py-3 text-slate-500">{providerLabel(cfg.provider)}</td>
                    <td className="px-4 py-3 text-slate-500 font-mono text-xs">{cfg.model}</td>
                    <td className="px-4 py-3 text-center text-slate-500">{cfg.priority}</td>
                    <td className="px-4 py-3 text-center">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                          cfg.is_active
                            ? 'bg-emerald-100 text-emerald-700'
                            : 'bg-slate-100 text-slate-500'
                        }`}
                      >
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${cfg.is_active ? 'bg-emerald-500' : 'bg-slate-400'}`}
                        />
                        {cfg.is_active ? '启用' : '禁用'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleOpenEdit(cfg)}
                          className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700
                                     hover:bg-slate-100 rounded-md transition-colors"
                        >
                          <i className="ri-pencil-line mr-1" />
                          编辑
                        </button>
                        <button
                          onClick={() => setDeleteTarget(cfg)}
                          className="px-2.5 py-1 text-xs text-red-500 hover:text-red-700
                                     hover:bg-red-50 rounded-md transition-colors"
                        >
                          <i className="ri-delete-bin-line mr-1" />
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

      {/* 新增/编辑弹窗 */}
      {showForm && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-[200]"
          onClick={() => setShowForm(false)}
        >
          <div
            className="bg-white rounded-xl w-full max-w-lg mx-4 shadow-xl max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
              <h2 className="font-semibold text-slate-800">
                {editingId !== null ? '编辑 LLM 配置' : '新增 LLM 配置'}
              </h2>
              <button
                onClick={() => setShowForm(false)}
                className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-slate-100 text-slate-400"
              >
                <i className="ri-close-line" />
              </button>
            </div>

            <div className="px-6 py-4 space-y-4">
              {formError && (
                <div className="px-4 py-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
                  {formError}
                </div>
              )}

              {/* 用途 */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">用途 (purpose)</label>
                <input
                  type="text"
                  value={form.purpose}
                  onChange={(e) => setForm({ ...form, purpose: e.target.value })}
                  placeholder="general / nl_query / summary ..."
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                />
              </div>

              {/* 显示名称 */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">显示名称</label>
                <input
                  type="text"
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  placeholder="GPT-4o Mini (General)"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                />
              </div>

              {/* Provider */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Provider</label>
                <select
                  value={form.provider}
                  onChange={(e) => {
                    const provider = e.target.value;
                    setForm({
                      ...form,
                      provider,
                      base_url:
                        provider === 'anthropic'
                          ? 'https://api.anthropic.com'
                          : 'https://api.openai.com/v1',
                      model:
                        provider === 'anthropic' ? 'claude-3-5-sonnet-20241022' : 'gpt-4o-mini',
                    });
                  }}
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                >
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </div>

              {/* Model */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Model</label>
                <input
                  type="text"
                  value={form.model}
                  onChange={(e) => setForm({ ...form, model: e.target.value })}
                  placeholder="gpt-4o-mini"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                />
              </div>

              {/* Base URL */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Base URL</label>
                <input
                  type="text"
                  value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  placeholder="https://api.openai.com/v1"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                />
              </div>

              {/* API Key */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  API Key
                  {editingId !== null && (
                    <span className="ml-1 text-xs font-normal text-slate-400">（留空则不更新）</span>
                  )}
                </label>
                <div className="relative">
                  <input
                    type={showApiKey ? 'text' : 'password'}
                    value={form.api_key}
                    onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                    placeholder={editingId !== null ? '留空不修改' : 'sk-...'}
                    className="w-full px-3 py-2 pr-10 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  >
                    <i className={showApiKey ? 'ri-eye-off-line' : 'ri-eye-line'} />
                  </button>
                </div>
              </div>

              {/* Temperature + Max Tokens */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Temperature</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={form.temperature}
                    onChange={(e) =>
                      setForm({ ...form, temperature: parseFloat(e.target.value) || 0.7 })
                    }
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Max Tokens</label>
                  <input
                    type="number"
                    min="1"
                    max="131072"
                    value={form.max_tokens}
                    onChange={(e) =>
                      setForm({ ...form, max_tokens: parseInt(e.target.value) || 1024 })
                    }
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              {/* Priority + is_active */}
              <div className="grid grid-cols-2 gap-4 items-end">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">
                    优先级（数字越大越优先）
                  </label>
                  <input
                    type="number"
                    min="0"
                    value={form.priority}
                    onChange={(e) =>
                      setForm({ ...form, priority: parseInt(e.target.value) || 0 })
                    }
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="flex items-center gap-2 cursor-pointer py-2">
                    <input
                      type="checkbox"
                      checked={form.is_active}
                      onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                      className="w-4 h-4 rounded border-slate-300 text-blue-500 focus:ring-blue-500"
                    />
                    <span className="text-sm text-slate-700">启用</span>
                  </label>
                </div>
              </div>
            </div>

            <div className="px-6 py-4 border-t border-slate-200 flex justify-end gap-3">
              <button
                onClick={() => setShowForm(false)}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 text-sm bg-slate-900 text-white rounded-lg hover:bg-slate-800
                           disabled:opacity-50 transition-colors"
              >
                {saving ? (
                  <span className="flex items-center gap-1.5">
                    <i className="ri-loader-4-line animate-spin" />
                    保存中...
                  </span>
                ) : editingId !== null ? '保存修改' : '创建配置'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认弹窗 */}
      <ConfirmModal
        open={!!deleteTarget}
        title="删除 LLM 配置"
        message={`确定删除配置「${deleteTarget?.display_name || deleteTarget?.purpose || ''}」吗？此操作不可撤销。`}
        confirmLabel="删除"
        variant="danger"
        loading={deleting}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
