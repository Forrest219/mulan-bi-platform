import { useState, useEffect } from 'react';
import { useAuth } from '../../../context/AuthContext';
import { getLLMConfig, saveLLMConfig, testLLMConnection, deleteLLMConfig } from '../../../api/llm';
import { ConfirmModal } from '../../../components/ConfirmModal';

const getErrorMessage = (error: unknown, fallback = '操作失败'): string => {
  return error instanceof Error ? error.message : fallback;
};

export default function LLMAdminPage() {
  const { user, hasPermission } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [confirmModal, setConfirmModal] = useState<{ open: boolean; title: string; message: string; onConfirm: () => void } | null>(null);
  const [testResult, setTestResult] = useState<string>('');
  const [showApiKey, setShowApiKey] = useState(false);

  // 表单状态
  const [form, setForm] = useState({
    provider: 'openai',
    base_url: 'https://api.openai.com/v1',
    api_key: '',
    model: 'gpt-4o-mini',
    temperature: 0.7,
    max_tokens: 1024,
    is_active: true,
  });

  // 加载配置
  useEffect(() => {
    loadConfig();
  }, []);

  // 权限检查（所有 hooks 之后）
  if (!user || (user.role !== 'admin' && !hasPermission('llm'))) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <div className="text-6xl mb-4">🔒</div>
          <h2 className="text-xl font-semibold text-slate-700 mb-2">无权限访问</h2>
          <p className="text-slate-500">您没有 LLM 配置管理权限</p>
        </div>
      </div>
    );
  }

  async function loadConfig() {
    setLoading(true);
    try {
      const data = await getLLMConfig();
      if (data.config) {
        setForm({
          provider: data.config.provider,
          base_url: data.config.base_url,
          api_key: '',  // 不显示已保存的 key
          model: data.config.model,
          temperature: data.config.temperature,
          max_tokens: data.config.max_tokens,
          is_active: data.config.is_active,
        });
      }
    } catch (e: unknown) {
      setMessage({ type: 'error', text: getErrorMessage(e) });
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    if (!form.api_key) {
      setMessage({ type: 'error', text: 'API Key 不能为空' });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await saveLLMConfig(form);
      setMessage({ type: 'success', text: 'LLM 配置保存成功' });
      setForm({ ...form, api_key: '' }); // 清空 api_key 字段
    } catch (e: unknown) {
      setMessage({ type: 'error', text: getErrorMessage(e) });
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult('');
    setMessage(null);
    try {
      const result = await testLLMConnection();
      setTestResult(result.success ? `✅ 成功: ${result.message}` : `❌ 失败: ${result.message}`);
    } catch (e: unknown) {
      setTestResult(`❌ 错误: ${getErrorMessage(e)}`);
    } finally {
      setTesting(false);
    }
  }

  async function handleDelete() {
    try {
      await deleteLLMConfig();
      setForm({
        provider: 'openai',
        base_url: 'https://api.openai.com/v1',
        api_key: '',
        model: 'gpt-4o-mini',
        temperature: 0.7,
        max_tokens: 1024,
        is_active: true,
      });
      setMessage({ type: 'success', text: 'LLM 配置已删除' });
    } catch (e: unknown) {
      setMessage({ type: 'error', text: getErrorMessage(e) });
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-500">加载中...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-2xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="w-5 h-5 flex items-center justify-center">
              <i className="ri-robot-line text-slate-500 text-base" />
            </span>
            <h1 className="text-lg font-semibold text-slate-800">LLM 配置</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">配置 LLM Provider 以启用 AI 解读功能</p>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-2xl mx-auto px-8 py-7">
        <div className="bg-white border border-slate-200 rounded-xl p-6">
          {message && (
            <div className={`mb-4 px-4 py-3 rounded-lg text-sm ${
              message.type === 'success' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-red-50 text-red-700 border border-red-200'
            }`}>
              {message.text}
            </div>
          )}

          {/* Provider */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-700 mb-1">Provider</label>
            <select
              value={form.provider}
              onChange={e => {
                const provider = e.target.value;
                if (provider === 'anthropic') {
                  setForm({
                    ...form,
                    provider,
                    base_url: 'https://api.minimaxi.com/anthropic',
                    model: 'MiniMax-M2.7',
                  });
                } else {
                  setForm({
                    ...form,
                    provider,
                    base_url: 'https://api.openai.com/v1',
                    model: 'gpt-4o-mini',
                  });
                }
              }}
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic（MiniMax 等）</option>
            </select>
          </div>

          {/* Base URL */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-700 mb-1">Base URL</label>
            <input
              type="text"
              value={form.base_url}
              onChange={e => setForm({ ...form, base_url: e.target.value })}
              placeholder="https://api.openai.com/v1"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* API Key */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-700 mb-1">API Key</label>
            <div className="relative">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={form.api_key}
                onChange={e => setForm({ ...form, api_key: e.target.value })}
                placeholder={form.api_key ? '已保存（不修改请留空）' : 'sk-...'}
                className="w-full px-3 py-2 pr-10 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                <i className={showApiKey ? 'ri-eye-off-line' : 'ri-eye-line'} />
              </button>
            </div>
          </div>

          {/* Model */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-700 mb-1">Model</label>
            <input
              type="text"
              value={form.model}
              onChange={e => setForm({ ...form, model: e.target.value })}
              placeholder="gpt-4o-mini"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* Temperature & Max Tokens */}
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Temperature</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={form.temperature}
                onChange={e => setForm({ ...form, temperature: parseFloat(e.target.value) || 0.7 })}
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Max Tokens</label>
              <input
                type="number"
                min="1"
                max="4096"
                value={form.max_tokens}
                onChange={e => setForm({ ...form, max_tokens: parseInt(e.target.value) || 1024 })}
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          {/* Active Toggle */}
          <div className="mb-6">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={e => setForm({ ...form, is_active: e.target.checked })}
                className="w-4 h-4 rounded border-slate-300 text-blue-500 focus:ring-blue-500"
              />
              <span className="text-sm text-slate-700">启用 LLM</span>
            </label>
          </div>

          {/* Buttons */}
          <div className="flex items-center gap-3 pt-4 border-t border-slate-100">
            <button
              onClick={handleTest}
              disabled={testing || !form.api_key}
              className="px-4 py-2 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {testing ? '测试中...' : '测试连接'}
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 text-sm bg-slate-900 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50 transition-colors"
            >
              {saving ? '保存中...' : '保存配置'}
            </button>
            <button
              onClick={() => {
                setConfirmModal({
                  open: true,
                  title: '删除 LLM 配置',
                  message: '确定要删除当前的 LLM 配置吗？此操作不可撤销。',
                  onConfirm: () => { setConfirmModal(null); handleDelete(); },
                });
              }}
              className="px-4 py-2 text-sm text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
            >
              删除配置
            </button>
          </div>

          {/* Test Result */}
          {testResult && (
            <div className={`mt-4 px-4 py-3 rounded-lg text-sm font-mono ${
              testResult.startsWith('✅') ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
            }`}>
              {testResult}
            </div>
          )}
        </div>
      </div>

      {/* 通用确认弹窗 */}
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
