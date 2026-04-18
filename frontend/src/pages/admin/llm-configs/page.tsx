/**
 * LLMConfigsPage — /system/llm-configs
 *
 * admin-only LLM 多配置管理页。
 *
 * 功能：
 * - 列表展示所有 LLM 配置（purpose、display_name、provider、model、API Key、运行状态、priority）
 * - 新增 / 编辑表单（含 API Key 掩码指纹 + 修改模式切换）
 * - 删除按钮（ConfirmModal）
 * - 行内启用/禁用切换（乐观更新 + Popconfirm）
 * - 列表行内测试连接 + 展开证据副行
 * - 仅 admin 可见
 *
 * 后端 API：
 *   GET    /api/llm/configs              → LLMConfigItem[]
 *   POST   /api/llm/configs              → LLMConfigItem
 *   PUT    /api/llm/configs/:id          → LLMConfigItem
 *   DELETE /api/llm/configs/:id          → 204
 *   PATCH  /api/llm/configs/:id/active   → LLMConfigItem
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from '../../../context/AuthContext';
import { ConfirmModal } from '../../../components/ConfirmModal';
import { apiToggleActive } from '../../../api/llm';

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
  api_key_preview?: string | null;
  api_key_updated_at?: string | null;
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

interface TestResult {
  success: boolean;
  message: string;
  response_text?: string;
  response_model?: string;
  latency_ms?: number;
  tokens_used?: number;
  prompt_used?: string;
  error_code?: string;
}

// 列表行内测试证据
interface TestEvidence {
  status: 'testing' | 'ok' | 'fail';
  response_text?: string;
  response_model?: string;
  latency_ms?: number;
  tokens_used?: number;
  error_code?: string;
  detail?: string;
}

const defaultForm: LLMConfigForm = {
  purpose: 'default',
  display_name: '',
  provider: 'minimax',
  model: 'MiniMax-2.7',
  base_url: 'https://api.minimaxi.com/anthropic',
  api_key: '',
  temperature: 0.7,
  max_tokens: 1024,
  is_active: true,
  priority: 0,
};

// ─── Utility ──────────────────────────────────────────────────────────────────

function formatRelativeTime(isoStr: string): string {
  const d = new Date(isoStr);
  const diff = Date.now() - d.getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return '今天';
  if (days === 1) return '昨天';
  if (days < 30) return `${days} 天前`;
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' });
}

function getDaysSince(isoStr: string): number {
  return Math.floor((Date.now() - new Date(isoStr).getTime()) / 86400000);
}

// ─── API helpers ──────────────────────────────────────────────────────────────

async function apiListConfigs(): Promise<LLMConfigItem[]> {
  const res = await fetch('/api/llm/configs', { credentials: 'include' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : (data.configs ?? []);
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

// ─── RunStatusBadge（4 态）────────────────────────────────────────────────────

type RunState = 'running' | 'checking' | 'error' | 'disabled';

function getRunState(
  cfg: LLMConfigItem,
  rowTestStatus?: 'idle' | 'testing' | 'ok' | 'fail',
): RunState {
  if (!cfg.is_active) return 'disabled';
  if (rowTestStatus === 'testing' || rowTestStatus === 'idle' || rowTestStatus === undefined) {
    return 'checking';
  }
  if (rowTestStatus === 'ok') return 'running';
  return 'error';
}

function RunStatusBadge({ state }: { state: RunState }) {
  const variants: Record<RunState, { dot: string; pill: string; label: string }> = {
    running:  { dot: 'bg-emerald-500',              pill: 'bg-emerald-50 text-emerald-700 border-emerald-200', label: '运行中' },
    checking: { dot: 'bg-slate-400 animate-pulse',  pill: 'bg-slate-100 text-slate-600 border-slate-200',     label: '检测中…' },
    error:    { dot: 'bg-red-500',                  pill: 'bg-red-50 text-red-700 border-red-200',            label: '连接异常' },
    disabled: { dot: 'bg-slate-300',                pill: 'bg-slate-100 text-slate-500 border-slate-200',     label: '未启用' },
  };
  const v = variants[state];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${v.pill}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${v.dot}`} />
      {v.label}
    </span>
  );
}

// ─── ApiKeyCell ───────────────────────────────────────────────────────────────

function ApiKeyCell({
  cfg,
  onSetupKey,
}: {
  cfg: LLMConfigItem;
  onSetupKey: () => void;
}) {
  const hasKey = cfg.has_api_key === true;

  if (!hasKey) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
        <span className="text-xs text-slate-500">未配置</span>
        <button
          onClick={onSetupKey}
          className="text-xs text-blue-600 hover:text-blue-700 underline-offset-2 hover:underline"
        >
          去设置
        </button>
      </div>
    );
  }

  const daysSince = cfg.api_key_updated_at ? getDaysSince(cfg.api_key_updated_at) : null;
  const isStale = daysSince !== null && daysSince >= 90;

  return (
    <div className="space-y-0.5">
      {cfg.has_api_key && (
        <code className="block truncate max-w-full text-xs font-mono text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">
          {cfg.api_key_preview || '••••••••'}
        </code>
      )}
      <div className="flex items-center gap-1.5 flex-wrap">
        {cfg.api_key_updated_at && (
          <span className="text-[11px] text-slate-400">
            更新于 {formatRelativeTime(cfg.api_key_updated_at)}
          </span>
        )}
        {isStale && (
          <span className="text-[11px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 font-medium">
            90+ 天未轮换
          </span>
        )}
      </div>
    </div>
  );
}

// ─── TestEvidenceRow ──────────────────────────────────────────────────────────

function TestEvidenceRow({ evidence }: { evidence: TestEvidence }) {
  if (evidence.status === 'testing') {
    return (
      <tr>
        <td colSpan={9} className="px-4 py-3 bg-slate-50 border-b border-slate-100">
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <span className="w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
            检测中…
          </div>
        </td>
      </tr>
    );
  }

  const isOk = evidence.status === 'ok';
  const borderColor = isOk ? 'border-l-emerald-500' : 'border-l-red-500';
  const bgColor = isOk ? 'bg-emerald-50' : 'bg-red-50';

  let errorMsg = '';
  if (!isOk) {
    const code = evidence.error_code ?? '';
    if (code === '401' || code.includes('401')) {
      errorMsg = '鉴权失败，请检查 API Key 是否正确或已过期';
    } else if (code === '404' || code.includes('404')) {
      errorMsg = 'Base URL 或 Model 名称不正确';
    } else if (code === 'timeout' || code === 'network' || code.includes('timeout') || code.includes('network')) {
      errorMsg = '请求超时或网络异常，请检查 Base URL 和代理设置';
    } else {
      errorMsg = evidence.detail || evidence.error_code || '连接失败，请检查配置';
    }
  }

  return (
    <tr>
      <td colSpan={9} className={`border-b border-slate-100 ${bgColor}`}>
        <div className={`ml-4 mr-4 my-2.5 pl-3 border-l-4 ${borderColor}`}>
          {isOk ? (
            <div className="space-y-1">
              <p className="text-sm text-emerald-800">
                模型实际答复：
                <span className="font-medium">&ldquo;{evidence.response_text}&rdquo;</span>
              </p>
              <p className="text-[11px] text-slate-500">
                {evidence.response_model && <span>实际模型: {evidence.response_model} · </span>}
                {evidence.latency_ms !== undefined && <span>{evidence.latency_ms}ms · </span>}
                {evidence.tokens_used !== undefined && <span>{evidence.tokens_used} tokens · </span>}
                刚刚
              </p>
            </div>
          ) : (
            <p className="text-sm text-red-700">{errorMsg}</p>
          )}
        </div>
      </td>
    </tr>
  );
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
  const [editingConfig, setEditingConfig] = useState<LLMConfigItem | null>(null);
  const [form, setForm] = useState<LLMConfigForm>(defaultForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // API Key 掩码 / 修改模式
  const [isEditingKey, setIsEditingKey] = useState(false);
  const [showKey, setShowKey] = useState(false);

  // 表单内测试连接
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [showTestDetail, setShowTestDetail] = useState(false);

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<LLMConfigItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  // 行内启用/禁用
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [confirmToggle, setConfirmToggle] = useState<{ cfg: LLMConfigItem } | null>(null);

  // 列表连接状态（用于 RunStatusBadge 4 态推导）
  type TestStatus = 'idle' | 'testing' | 'ok' | 'fail';
  const [rowTestStatus, setRowTestStatus] = useState<Record<number, TestStatus>>({});
  const rowTestStatusRef = useRef(rowTestStatus);
  rowTestStatusRef.current = rowTestStatus;

  // 列表行内测试证据（改造 2）
  const [testEvidenceMap, setTestEvidenceMap] = useState<Record<number, TestEvidence>>({});
  // 当前展开证据副行的 config_id
  const [expandedEvidenceId, setExpandedEvidenceId] = useState<number | null>(null);

  const testAllActive = useCallback(async (cfgList: LLMConfigItem[]) => {
    const active = cfgList.filter(c => c.is_active);
    if (active.length === 0) return;

    setRowTestStatus(prev => {
      const next = { ...prev };
      active.forEach(c => { next[c.id] = 'testing'; });
      return next;
    });

    await Promise.all(active.map(async (cfg) => {
      try {
        const res = await fetch('/api/llm/config/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ prompt: 'Say OK in one word', config_id: cfg.id }),
        });
        const data = await res.json();
        setRowTestStatus(prev => ({ ...prev, [cfg.id]: data.success ? 'ok' : 'fail' }));
      } catch {
        setRowTestStatus(prev => ({ ...prev, [cfg.id]: 'fail' }));
      }
    }));
  }, []);

  const loadConfigs = useCallback(() => {
    setLoading(true);
    setError(null);
    apiListConfigs()
      .then((list) => {
        setConfigs(list);
        testAllActive(list);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [testAllActive]);

  useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  // 每 5 分钟自动重新检测所有活跃配置连接状态
  useEffect(() => {
    const timer = setInterval(() => {
      testAllActive(configs);
    }, 5 * 60 * 1000);
    return () => clearInterval(timer);
  }, [configs, testAllActive]);

  // ── 行内启用/禁用 ──────────────────────────────────────────────────────────

  const doToggle = async (cfg: LLMConfigItem, newActive: boolean) => {
    setTogglingId(cfg.id);
    setConfigs(prev => prev.map(c => c.id === cfg.id ? { ...c, is_active: newActive } : c));
    try {
      await apiToggleActive(cfg.id, newActive);
    } catch (e) {
      setConfigs(prev => prev.map(c => c.id === cfg.id ? { ...c, is_active: !newActive } : c));
      setError(e instanceof Error ? e.message : '操作失败');
    } finally {
      setTogglingId(null);
    }
  };

  const handleToggleActive = (cfg: LLMConfigItem) => {
    if (cfg.is_active) {
      setConfirmToggle({ cfg });
    } else {
      doToggle(cfg, true);
    }
  };

  // ── 列表行内测试（改造 2）─────────────────────────────────────────────────

  const handleRowTest = async (cfg: LLMConfigItem) => {
    // 已经展开同一行 → 收起
    if (expandedEvidenceId === cfg.id && testEvidenceMap[cfg.id]?.status !== 'testing') {
      setExpandedEvidenceId(null);
      return;
    }

    setExpandedEvidenceId(cfg.id);
    setTestEvidenceMap(prev => ({ ...prev, [cfg.id]: { status: 'testing' } }));

    try {
      const res = await fetch('/api/llm/config/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ prompt: 'Say OK in one word', config_id: cfg.id }),
      });
      const data = await res.json();
      if (data.success) {
        setTestEvidenceMap(prev => ({
          ...prev,
          [cfg.id]: {
            status: 'ok',
            response_text: data.response_text,
            response_model: data.response_model,
            latency_ms: data.latency_ms,
            tokens_used: data.tokens_used,
          },
        }));
        setRowTestStatus(prev => ({ ...prev, [cfg.id]: 'ok' }));
      } else {
        setTestEvidenceMap(prev => ({
          ...prev,
          [cfg.id]: {
            status: 'fail',
            error_code: data.error_code ?? String(res.status),
            detail: data.message ?? data.detail,
          },
        }));
        setRowTestStatus(prev => ({ ...prev, [cfg.id]: 'fail' }));
      }
    } catch {
      setTestEvidenceMap(prev => ({
        ...prev,
        [cfg.id]: { status: 'fail', error_code: 'network', detail: '请求异常' },
      }));
      setRowTestStatus(prev => ({ ...prev, [cfg.id]: 'fail' }));
    }
  };

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

  const handleClose = () => {
    setShowForm(false);
    setTestResult(null);
    setTesting(false);
    setIsEditingKey(false);
    setShowKey(false);
    setShowTestDetail(false);
  };

  const handleOpenNew = () => {
    setEditingId(null);
    setEditingConfig(null);
    setForm(defaultForm);
    setFormError(null);
    setTestResult(null);
    setIsEditingKey(false);
    setShowKey(false);
    setShowTestDetail(false);
    setShowForm(true);
  };

  const handleOpenEdit = (cfg: LLMConfigItem, focusKey = false) => {
    setEditingId(cfg.id);
    setEditingConfig(cfg);
    setForm({
      purpose: cfg.purpose,
      display_name: cfg.display_name,
      provider: cfg.provider,
      model: cfg.model,
      base_url: cfg.base_url,
      api_key: '',
      temperature: cfg.temperature,
      max_tokens: cfg.max_tokens,
      is_active: cfg.is_active,
      priority: cfg.priority,
    });
    setFormError(null);
    setTestResult(null);
    setIsEditingKey(focusKey);
    setShowKey(false);
    setShowTestDetail(false);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (editingId === null && !form.api_key?.trim()) {
      setFormError('API Key 不能为空');
      return;
    }
    if (!form.model?.trim()) {
      setFormError('Model 名称不能为空');
      return;
    }
    if (form.base_url && !form.base_url.startsWith('http')) {
      setFormError('Base URL 必须以 http:// 或 https:// 开头');
      return;
    }

    setFormError(null);
    setSaving(true);
    try {
      if (editingId !== null) {
        const payload: Partial<LLMConfigForm> = { ...form };
        if (!payload.api_key) delete payload.api_key;
        await apiUpdateConfig(editingId, payload);
      } else {
        await apiCreateConfig(form);
      }
      handleClose();
      loadConfigs();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes('409') || msg.includes('显示名称')) {
        setFormError('显示名称已存在，请更换');
        return;
      }
      setFormError(msg);
    } finally {
      setSaving(false);
    }
  };

  // 表单内测试连接（保留原有逻辑）
  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    setShowTestDetail(false);
    try {
      const body: Record<string, unknown> = { prompt: 'Say OK in one word' };
      if (editingId === null) {
        body.base_url = form.base_url;
        body.api_key = form.api_key;
        body.model = form.model;
        body.provider = form.provider;
      } else {
        body.config_id = editingId;
        body.provider = form.provider;
      }
      const res = await fetch('/api/llm/config/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      });
      const data = await res.json();
      setTestResult({
        success: data.success ?? false,
        message: data.message ?? (data.success ? '连接正常' : '连接失败'),
        response_text: data.response_text,
        response_model: data.response_model,
        latency_ms: data.latency_ms,
        tokens_used: data.tokens_used,
        prompt_used: data.prompt_used,
        error_code: data.error_code,
      });
    } catch {
      setTestResult({ success: false, message: '请求异常，请检查网络' });
    } finally {
      setTesting(false);
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

  const providerLabel = (p: string) => ({
    minimax: 'MiniMax',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    'openai-compatible': 'OpenAI Compatible',
  }[p] ?? p);

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              {showForm ? (
                <button
                  onClick={handleClose}
                  className="flex items-center gap-1 text-slate-400 hover:text-slate-600 transition-colors"
                >
                  <i className="ri-arrow-left-line text-base" />
                </button>
              ) : (
                <i className="ri-robot-2-line text-slate-500 text-base" />
              )}
              <h1 className="text-lg font-semibold text-slate-800">
                {showForm
                  ? (editingId !== null ? '编辑 LLM 配置' : '新增 LLM 配置')
                  : 'LLM 多配置管理'}
              </h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-6">
              {showForm
                ? '填写完成后点击右下角「保存」，或点击左侧箭头返回列表'
                : '管理不同用途的 LLM Provider 配置（多配置支持按 purpose 选择）'}
            </p>
          </div>
          {!showForm && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => testAllActive(configs)}
                className="flex items-center gap-1 px-3 py-2 text-sm text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
                title="检测所有配置的连接可用性"
              >
                <i className="ri-refresh-line" />
                重新检测连接
              </button>
              <button
                onClick={handleOpenNew}
                className="flex items-center gap-1.5 px-4 py-2 bg-slate-900 text-white text-sm
                           rounded-lg hover:bg-slate-800 transition-colors"
              >
                <i className="ri-add-line" />
                新增配置
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-7xl mx-auto px-8 py-7">
        {/* ── 列表视图 ──────────────────────────────────────────────── */}
        {!showForm && <>

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
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Provider · Model</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600 w-40">API Key</th>
                  <th className="px-4 py-3 text-center font-medium text-slate-600 w-20">优先级</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600 min-w-[120px]">连接状态</th>
                  <th className="px-4 py-3 text-center font-medium text-slate-600">启用</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">操作</th>
                </tr>
              </thead>
              <tbody>
                {configs.map((cfg) => {
                  const runState = getRunState(cfg, rowTestStatus[cfg.id]);
                  const isToggling = togglingId === cfg.id;
                  const evidence = testEvidenceMap[cfg.id];
                  const evidenceExpanded = expandedEvidenceId === cfg.id;

                  return (
                    <>
                      <tr key={cfg.id} className="border-b border-slate-100 hover:bg-slate-50 transition-colors align-middle">
                        <td className="px-4 py-3 align-middle">
                          <span className="px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded-md font-mono">
                            {cfg.purpose}
                          </span>
                        </td>
                        <td className="px-4 py-3 align-middle text-slate-700 font-medium">{cfg.display_name || '-'}</td>
                        <td className="px-4 py-3 align-middle">
                          <div className="text-slate-500 text-xs">{providerLabel(cfg.provider)}</div>
                          <div className="text-slate-500 font-mono text-xs">{cfg.model}</div>
                        </td>
                        <td className="px-4 py-3 align-middle w-40 max-w-[200px]">
                          <ApiKeyCell
                            cfg={cfg}
                            onSetupKey={() => handleOpenEdit(cfg, true)}
                          />
                        </td>
                        <td className="px-4 py-3 align-middle text-center text-slate-500 w-20">{cfg.priority}</td>
                        <td className="px-4 py-3 align-middle min-w-[120px]">
                          <RunStatusBadge state={runState} />
                        </td>
                        <td className="px-4 py-3 align-middle text-center">
                          {/* toggle switch */}
                          <label className="relative inline-flex items-center cursor-pointer">
                            <input
                              type="checkbox"
                              role="switch"
                              className="sr-only peer"
                              checked={cfg.is_active}
                              disabled={isToggling}
                              onChange={() => handleToggleActive(cfg)}
                            />
                            <div className={`
                              w-8 h-4 rounded-full transition-colors
                              peer-disabled:opacity-50
                              ${cfg.is_active ? 'bg-emerald-500' : 'bg-slate-300'}
                              peer-focus-visible:ring-2 peer-focus-visible:ring-emerald-400 peer-focus-visible:ring-offset-1
                            `}>
                              <div className={`
                                absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full shadow-sm transition-transform
                                ${cfg.is_active ? 'translate-x-4' : 'translate-x-0'}
                              `} />
                            </div>
                          </label>
                        </td>
                        <td className="px-4 py-3 align-middle">
                          <div className="flex items-center justify-start gap-1.5">
                            <button
                              onClick={() => handleRowTest(cfg)}
                              disabled={evidence?.status === 'testing' || !cfg.has_api_key}
                              title={!cfg.has_api_key ? '请先配置 API Key' : undefined}
                              className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700
                                         hover:bg-slate-100 rounded-md transition-colors flex items-center gap-1
                                         disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                              <i className={`${evidence?.status === 'testing' ? 'ri-loader-4-line animate-spin' : 'ri-pulse-line'}`} />
                              测试
                            </button>
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
                      {/* 证据副行 */}
                      {evidenceExpanded && evidence && (
                        <TestEvidenceRow key={`evidence-${cfg.id}`} evidence={evidence} />
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        </> /* 列表视图结束 */}

        {/* ── 内嵌表单视图 ──────────────────────────────────────────── */}
        {showForm && (
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
            <div className="px-6 py-4 space-y-0">
              {formError && (
                <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
                  {formError}
                </div>
              )}

              {/* 组 A：身份识别 */}
              <div className="border-t border-slate-100 pt-4 mt-4">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
                  身份识别
                </p>

                {/* 显示名称 */}
                <div className="mb-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">显示名称</label>
                  <input
                    type="text"
                    value={form.display_name}
                    onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                    placeholder="GPT-4o Mini (General)"
                    maxLength={100}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>

                {/* 用途 */}
                <div className="mb-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">用途 (purpose)</label>
                  <select
                    value={form.purpose}
                    onChange={(e) => setForm({ ...form, purpose: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  >
                    <option value="default">default — 通用默认</option>
                    <option value="nl_query">nl_query — 自然语言查询</option>
                    <option value="summary">summary — 数据摘要</option>
                  </select>
                </div>
              </div>

              {/* 组 B：Provider 连接 */}
              <div className="border-t border-slate-100 pt-4 mt-4">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
                  Provider 连接
                </p>

                {/* Provider */}
                <div className="mb-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">Provider</label>
                  <select
                    value={form.provider}
                    onChange={(e) => {
                      const provider = e.target.value;
                      const presets: Record<string, { base_url: string; model: string }> = {
                        minimax:            { base_url: 'https://api.minimaxi.com/anthropic',   model: 'MiniMax-2.7' },
                        openai:             { base_url: 'https://api.openai.com/v1',            model: 'gpt-4o-mini' },
                        'openai-compatible':{ base_url: '',                                     model: '' },
                        anthropic:          { base_url: 'https://api.anthropic.com',            model: 'claude-3-5-sonnet-20241022' },
                      };
                      const preset = presets[provider] ?? { base_url: '', model: '' };
                      setForm({ ...form, provider, ...preset });
                    }}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  >
                    <option value="minimax">MiniMax</option>
                    <option value="openai">OpenAI</option>
                    <option value="openai-compatible">OpenAI Compatible（第三方）</option>
                    <option value="anthropic">Anthropic</option>
                  </select>
                </div>

                {/* Base URL */}
                <div className="mb-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">Base URL</label>
                  <input
                    type="text"
                    value={form.base_url}
                    onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                    placeholder="https://api.openai.com/v1"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>

                {/* API Key — 编辑态（只读/可编辑）vs 新建态 */}
                <div className="mb-4">
                  {editingId !== null ? (
                    // ── 编辑态 ──────────────────────────────────────────
                    <>
                      <label className="block text-sm font-medium text-slate-700 mb-1">API Key</label>
                      {!isEditingKey ? (
                        // 只读态
                        editingConfig?.has_api_key ? (
                          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="text-slate-400 text-xs">API Key</span>
                              {editingConfig.api_key_preview && (
                                <code className="text-sm font-mono text-slate-700">{editingConfig.api_key_preview}</code>
                              )}
                              <span className="text-xs bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded">已配置</span>
                            </div>
                            <div className="flex items-center gap-3 text-xs text-slate-400">
                              {editingConfig.api_key_updated_at && (
                                <span>更新于 {formatRelativeTime(editingConfig.api_key_updated_at)}</span>
                              )}
                              <button
                                type="button"
                                onClick={() => setIsEditingKey(true)}
                                className="text-blue-600 hover:text-blue-700 font-medium"
                              >
                                修改 Key
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <i className="ri-error-warning-line text-red-500" />
                              <span className="text-sm text-red-700">尚未配置 API Key，此配置将无法调用</span>
                            </div>
                            <button
                              type="button"
                              onClick={() => setIsEditingKey(true)}
                              className="text-sm text-blue-600 font-medium"
                            >
                              设置 Key
                            </button>
                          </div>
                        )
                      ) : (
                        // 可编辑态
                        <div className="space-y-1.5">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded">将在保存时替换</span>
                            <button
                              type="button"
                              onClick={() => { setIsEditingKey(false); setForm(f => ({ ...f, api_key: '' })); }}
                              className="text-xs text-slate-400 hover:text-slate-600"
                            >
                              取消修改
                            </button>
                          </div>
                          <div className="relative">
                            <input
                              type={showKey ? 'text' : 'password'}
                              autoComplete="new-password"
                              value={form.api_key}
                              onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))}
                              placeholder="输入新的 API Key"
                              className="w-full px-3 py-2 border border-amber-300 rounded-lg text-sm focus:outline-none focus:border-amber-500 font-mono pr-10"
                            />
                            <button
                              type="button"
                              onClick={() => setShowKey(v => !v)}
                              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                            >
                              <i className={showKey ? 'ri-eye-off-line' : 'ri-eye-line'} />
                            </button>
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    // ── 新建态 ──────────────────────────────────────────
                    <>
                      <label className="block text-sm font-medium text-slate-700 mb-1">
                        API Key
                        <span className="text-red-500 ml-0.5">*</span>
                      </label>
                      <div className="relative">
                        <input
                          type={showKey ? 'text' : 'password'}
                          autoComplete="new-password"
                          value={form.api_key}
                          onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                          placeholder="sk-..."
                          className="w-full px-3 py-2 pr-10 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 font-mono"
                        />
                        <button
                          type="button"
                          onClick={() => setShowKey(v => !v)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                          tabIndex={-1}
                        >
                          <i className={showKey ? 'ri-eye-off-line' : 'ri-eye-line'} />
                        </button>
                      </div>
                    </>
                  )}
                </div>

                {/* Model */}
                <div className="mb-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">Model</label>
                  <input
                    type="text"
                    value={form.model}
                    onChange={(e) => setForm({ ...form, model: e.target.value })}
                    placeholder="gpt-4o-mini"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              {/* 组 C：调用参数 */}
              <div className="border-t border-slate-100 pt-4 mt-4">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
                  调用参数
                </p>

                {/* Temperature + Max Tokens */}
                <div className="grid grid-cols-2 gap-3 mb-4">
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

                {/* Priority */}
                <div className="mb-4">
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
                {/* is_active 已移至列表行内 toggle，表单不再提供 */}
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between pt-4 border-t border-slate-100 mt-4 px-6 pb-5">
              {/* 左端：测试连接 + 证据卡 */}
              <div className="flex flex-col gap-2 flex-1 mr-4">
                <div className="flex items-center gap-3">
                  <button
                    onClick={handleTestConnection}
                    disabled={testing || !form.base_url || (editingId === null && !form.api_key)}
                    title={
                      !form.base_url ? '填写 Base URL 后可测试' :
                      (editingId === null && !form.api_key) ? '填写 API Key 后可测试' :
                      undefined
                    }
                    className="px-3 py-1.5 text-xs border border-slate-200 text-slate-500 rounded-lg
                               hover:bg-slate-50 transition-colors flex items-center gap-1.5
                               disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                  >
                    <i className={`text-xs ${testing ? 'ri-loader-4-line animate-spin' : 'ri-signal-wifi-line'}`} />
                    {testing ? '测试中...' : '测试连接'}
                  </button>
                </div>

                {/* 测试连接证据卡 */}
                {testResult && (
                  <div className={`rounded-lg border p-3 text-sm ${testResult.success ? 'border-emerald-200 bg-emerald-50' : 'border-red-200 bg-red-50'}`}>
                    {/* 顶部行 */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <i className={testResult.success ? 'ri-checkbox-circle-line text-emerald-600' : 'ri-close-circle-line text-red-600'} />
                        <span className={`font-medium ${testResult.success ? 'text-emerald-700' : 'text-red-700'}`}>
                          {testResult.message}
                        </span>
                        {testResult.success && testResult.latency_ms && (
                          <span className="text-xs text-slate-400">· {testResult.latency_ms}ms</span>
                        )}
                        {testResult.success && testResult.tokens_used && (
                          <span className="text-xs text-slate-400">· {testResult.tokens_used} tokens</span>
                        )}
                      </div>
                      {testResult.success && testResult.response_text && (
                        <button
                          onClick={() => setShowTestDetail(v => !v)}
                          className="text-xs text-slate-500 hover:text-slate-700 flex items-center gap-1"
                        >
                          查看回答 <i className={showTestDetail ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'} />
                        </button>
                      )}
                    </div>

                    {/* 展开的证据 */}
                    {showTestDetail && testResult.success && (
                      <div className="mt-3 space-y-1.5 border-t border-emerald-200 pt-3">
                        <div className="text-xs text-slate-500">问：<span className="text-slate-700">{testResult.prompt_used || 'Say OK in one word'}</span></div>
                        <div className="text-xs text-slate-500">答：
                          <code className="ml-1 bg-white border border-emerald-100 rounded px-2 py-0.5 text-slate-700">{testResult.response_text}</code>
                        </div>
                        {testResult.response_model && (
                          <div className="text-xs text-slate-400">实际模型：{testResult.response_model}</div>
                        )}
                      </div>
                    )}

                    {/* 失败时的错误详情（不折叠）*/}
                    {!testResult.success && (
                      <div className="mt-2 flex items-start justify-between">
                        <p className="text-xs text-red-600 font-mono">{testResult.message}</p>
                        <button
                          onClick={() => navigator.clipboard.writeText(testResult.message)}
                          className="text-xs text-slate-400 hover:text-slate-600 ml-2 shrink-0"
                        >
                          复制
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* 右端：取消 + 保存 */}
              <div className="flex gap-2 shrink-0">
                <button
                  onClick={handleClose}
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

      </div>{/* Content end */}

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

      {/* 禁用确认 Popconfirm */}
      {confirmToggle && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/20" onClick={() => setConfirmToggle(null)} />
          <div className="relative bg-white rounded-xl shadow-xl border border-slate-200 p-5 max-w-sm w-full mx-4">
            <h3 className="text-sm font-semibold text-slate-800">禁用 {confirmToggle.cfg.display_name || confirmToggle.cfg.provider}？</h3>
            <p className="mt-1.5 text-sm text-slate-500">禁用后，此 purpose 的调用将回退到下一个优先级配置。若无其他可用配置，相关功能将暂停服务。</p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setConfirmToggle(null)}
                className="px-3 py-1.5 text-sm text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50"
              >
                取消
              </button>
              <button
                onClick={() => { doToggle(confirmToggle.cfg, false); setConfirmToggle(null); }}
                className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700"
              >
                确认禁用
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
