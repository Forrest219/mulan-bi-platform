/**
 * McpConfigsPage — /system/mcp-configs
 *
 * admin-only MCP 统一配置管理页。
 *
 * 功能：
 * - 列表展示所有 MCP 服务器配置（type badge、name、server_url、is_active toggle）
 * - 新增 / 编辑内嵌表单
 * - 连接测试（显示延迟或错误）
 * - 删除按钮（ConfirmModal）
 * - 问数配置：为每个 Tableau 连接配置 Connected App 密钥（T-09）
 *
 * 后端 API：
 *   GET    /api/mcp-configs/         → McpServerItem[]
 *   POST   /api/mcp-configs/         → McpServerItem
 *   PUT    /api/mcp-configs/:id      → McpServerItem
 *   DELETE /api/mcp-configs/:id      → { ok: true }
 *   POST   /api/mcp-configs/:id/test → { status, latency_ms, ... }
 *
 * T-09 新增 API：
 *   GET    /api/admin/query/connected-app?connection_id=<id>  → ConnectedAppStatus
 *   PUT    /api/admin/query/connected-app                     → { ok, connection_id, ... }
 *   DELETE /api/admin/query/connected-app?connection_id=<id>  → { ok, deactivated }
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../../context/AuthContext';
import { ConfirmModal } from '../../../components/ConfirmModal';

// ─── Types ────────────────────────────────────────────────────────────────────

interface McpServerItem {
  id: number;
  name: string;
  type: string;
  server_url: string;
  description: string | null;
  is_active: boolean;
  credentials: Record<string, string> | null;
  created_at: string;
  updated_at: string;
}

interface McpServerForm {
  name: string;
  type: string;
  server_url: string;
  description: string;
  is_active: boolean;
  credentials: Record<string, string>;
}

interface TestResult {
  status: 'online' | 'offline';
  latency_ms: number;
  http_status?: number;
  error?: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const TYPE_META: Record<string, { icon: string; cls: string; label: string }> = {
  tableau:   { icon: 'ri-bar-chart-2-line', cls: 'bg-blue-100 text-blue-700',    label: 'Tableau' },
  starrocks: { icon: 'ri-database-2-line',  cls: 'bg-orange-100 text-orange-700', label: 'StarRocks' },
};

const TYPE_META_FALLBACK = { icon: 'ri-plug-line', cls: 'bg-slate-100 text-slate-600', label: '未知' };

const URL_PLACEHOLDERS: Record<string, string> = {
  tableau:   'http://localhost:3927/tableau-mcp',
  starrocks: 'http://localhost:8000/mcp',
};

const defaultForm: McpServerForm = {
  name: '',
  type: 'tableau',
  server_url: '',
  description: '',
  is_active: true,
  credentials: {},
};

// ─── API helpers ──────────────────────────────────────────────────────────────

const API_BASE = '/api/mcp-configs';

async function apiList(): Promise<McpServerItem[]> {
  const res = await fetch(`${API_BASE}/`, { credentials: 'include' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function apiCreate(data: McpServerForm): Promise<McpServerItem> {
  const res = await fetch(`${API_BASE}/`, {
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

async function apiUpdate(id: number, data: Partial<McpServerForm> & { credentials?: Record<string, string> }): Promise<McpServerItem> {
  const res = await fetch(`${API_BASE}/${id}`, {
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

async function apiDelete(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
}

async function apiTest(id: number): Promise<TestResult> {
  const res = await fetch(`${API_BASE}/${id}/test`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── TypeBadge ───────────────────────────────────────────────────────────────

function TypeBadge({ type }: { type: string }) {
  const meta = TYPE_META[type] ?? TYPE_META_FALLBACK;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${meta.cls}`}>
      <i className={meta.icon} />
      {meta.label}
    </span>
  );
}

// ─── CredentialSection / CredentialField ─────────────────────────────────────

function CredentialSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4 border border-slate-100 rounded-lg p-4 bg-slate-50">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">{title}</p>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function CredentialField({
  label,
  fieldKey,
  placeholder,
  sensitive = false,
  readOnly = false,
  form,
  setForm,
}: {
  label: string;
  fieldKey: string;
  placeholder: string;
  sensitive?: boolean;
  readOnly?: boolean;
  form: McpServerForm;
  setForm: React.Dispatch<React.SetStateAction<McpServerForm>>;
}) {
  const [show, setShow] = useState(false);
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      <div className="relative">
        <input
          type={sensitive && !show ? 'password' : 'text'}
          value={form.credentials[fieldKey] ?? ''}
          readOnly={readOnly}
          onChange={(e) =>
            setForm({ ...form, credentials: { ...form.credentials, [fieldKey]: e.target.value } })
          }
          placeholder={placeholder}
          className={`w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none ${readOnly ? 'bg-slate-50 text-slate-600 cursor-default' : 'focus:border-blue-500 bg-white'}`}
        />
        {sensitive && (
          <button
            type="button"
            onClick={() => setShow((v) => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
          >
            <i className={show ? 'ri-eye-off-line' : 'ri-eye-line'} />
          </button>
        )}
      </div>
    </div>
  );
}

// ─── T-09: Connected App 密钥配置相关类型和 API ──────────────────────────────

interface TableauConnectionItem {
  id: number;
  name: string;
  server_url: string;
  site: string;
  is_active: boolean;
}

interface ConnectedAppStatus {
  configured: boolean;
  connection_id: number | null;
  client_id: string | null;
  secret_masked: string | null;
  is_active: boolean | null;
  created_at: string | null;
}

const QUERY_ADMIN_BASE = '/api/admin/query';

async function apiGetConnectedApp(connectionId: number): Promise<ConnectedAppStatus> {
  const res = await fetch(`${QUERY_ADMIN_BASE}/connected-app?connection_id=${connectionId}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiUpsertConnectedApp(data: {
  connection_id: number;
  client_id: string;
  secret_value: string;
}): Promise<{ ok: boolean; connection_id: number; client_id: string; is_active: boolean; created_at: string }> {
  const res = await fetch(`${QUERY_ADMIN_BASE}/connected-app`, {
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

async function apiDeactivateConnectedApp(connectionId: number): Promise<{ ok: boolean; deactivated: number }> {
  const res = await fetch(
    `${QUERY_ADMIN_BASE}/connected-app?connection_id=${connectionId}`,
    { method: 'DELETE', credentials: 'include' }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── ConnectedAppPanel ────────────────────────────────────────────────────────
// 单个 Tableau 连接的 Connected App 密钥配置折叠面板

function ConnectedAppPanel({
  connection,
  onToast,
}: {
  connection: TableauConnectionItem;
  onToast: (msg: string, variant?: 'success' | 'error') => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState<ConnectedAppStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [clientId, setClientId] = useState('');
  const [secretValue, setSecretValue] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deactivating, setDeactivating] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadStatus = useCallback(() => {
    setLoadingStatus(true);
    apiGetConnectedApp(connection.id)
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setLoadingStatus(false));
  }, [connection.id]);

  // 展开时加载状态
  useEffect(() => {
    if (expanded && status === null) {
      loadStatus();
    }
  }, [expanded, status, loadStatus]);

  const handleSave = async () => {
    if (!clientId.trim()) {
      setFormError('Client ID 不能为空');
      return;
    }
    if (!secretValue.trim()) {
      setFormError('Secret Value 不能为空');
      return;
    }
    setFormError(null);
    setSaving(true);
    try {
      await apiUpsertConnectedApp({
        connection_id: connection.id,
        client_id: clientId.trim(),
        secret_value: secretValue,
      });
      setClientId('');
      setSecretValue('');
      setStatus(null); // 触发重新加载
      loadStatus();
      onToast('Connected App 密钥已保存', 'success');
    } catch (e: unknown) {
      onToast(e instanceof Error ? e.message : '保存失败', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleDeactivate = async () => {
    setDeactivating(true);
    try {
      await apiDeactivateConnectedApp(connection.id);
      setStatus(null);
      loadStatus();
      onToast('Connected App 密钥已停用', 'success');
    } catch (e: unknown) {
      onToast(e instanceof Error ? e.message : '停用失败', 'error');
    } finally {
      setDeactivating(false);
      setConfirmDeactivate(false);
    }
  };

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      {/* 折叠标题行 */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-white hover:bg-slate-50 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <i className="ri-bar-chart-2-line text-blue-500 text-base" />
          <div>
            <span className="text-sm font-medium text-slate-700">{connection.name}</span>
            <span className="ml-2 text-xs text-slate-400">{connection.server_url}</span>
          </div>
          {/* 已配置徽标 */}
          {status?.configured === true && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">
              <i className="ri-checkbox-circle-line" />
              已配置
            </span>
          )}
          {status?.configured === false && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
              <i className="ri-error-warning-line" />
              未配置
            </span>
          )}
        </div>
        <i className={`text-slate-400 transition-transform ${expanded ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'}`} />
      </button>

      {/* 折叠内容 */}
      {expanded && (
        <div className="px-4 pb-4 pt-3 border-t border-slate-100 bg-slate-50 space-y-4">
          {/* 当前状态 */}
          {loadingStatus && (
            <div className="flex items-center gap-2 text-slate-400 text-sm py-2">
              <span className="w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
              加载中...
            </div>
          )}

          {!loadingStatus && status?.configured && (
            <div className="bg-white border border-slate-200 rounded-lg p-3 space-y-1.5">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">当前配置</p>
              <div className="flex items-center gap-2 text-sm">
                <span className="text-slate-500 w-24 shrink-0">Client ID</span>
                <code className="text-slate-700 font-mono text-xs bg-slate-50 px-2 py-0.5 rounded">
                  {status.client_id}
                </code>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <span className="text-slate-500 w-24 shrink-0">Secret</span>
                <code className="text-slate-700 font-mono text-xs bg-slate-50 px-2 py-0.5 rounded">
                  {status.secret_masked}
                </code>
              </div>
              {status.created_at && (
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-slate-500 w-24 shrink-0">配置时间</span>
                  <span className="text-slate-600 text-xs">{new Date(status.created_at).toLocaleString('zh-CN')}</span>
                </div>
              )}
            </div>
          )}

          {/* 表单区 */}
          <div className="space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
              {status?.configured ? '更新密钥' : '配置密钥'}
            </p>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Client ID <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={clientId}
                onChange={(e) => { setClientId(e.target.value); setFormError(null); }}
                placeholder="Connected App Client ID（从 Tableau 管理后台获取）"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 bg-white"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Secret Value <span className="text-red-400">*</span>
              </label>
              <div className="relative">
                <input
                  type={showSecret ? 'text' : 'password'}
                  value={secretValue}
                  onChange={(e) => { setSecretValue(e.target.value); setFormError(null); }}
                  placeholder="Connected App Secret Value（HS256 签名密钥）"
                  className="w-full px-3 py-2 pr-10 border border-slate-200 rounded-lg text-sm focus:outline-none focus:border-blue-500 bg-white"
                />
                <button
                  type="button"
                  onClick={() => setShowSecret((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  tabIndex={-1}
                >
                  <i className={showSecret ? 'ri-eye-off-line' : 'ri-eye-line'} />
                </button>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">
                仅用于签发 JWT，保存后不再回显。更新时重新填写即可覆盖旧密钥。
              </p>
            </div>

            {formError && (
              <div className="px-3 py-2 bg-red-50 border border-red-200 text-red-600 text-xs rounded-lg flex items-center gap-1.5">
                <i className="ri-error-warning-line" />
                {formError}
              </div>
            )}

            {/* 操作按钮 */}
            <div className="flex items-center gap-2 pt-1">
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 px-4 py-2 bg-slate-900 text-white text-xs rounded-lg hover:bg-slate-800 disabled:opacity-50 transition-colors"
              >
                {saving ? (
                  <>
                    <i className="ri-loader-4-line animate-spin" />
                    保存中...
                  </>
                ) : (
                  <>
                    <i className="ri-save-line" />
                    保存密钥
                  </>
                )}
              </button>

              {status?.configured && !confirmDeactivate && (
                <button
                  type="button"
                  onClick={() => setConfirmDeactivate(true)}
                  className="flex items-center gap-1.5 px-4 py-2 text-xs text-red-500 border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
                >
                  <i className="ri-forbid-line" />
                  停用配置
                </button>
              )}

              {/* 二次确认停用 */}
              {confirmDeactivate && (
                <div className="flex items-center gap-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg">
                  <span className="text-xs text-red-600">确认停用？停用后问数将无法使用 JWT 鉴权。</span>
                  <button
                    type="button"
                    onClick={handleDeactivate}
                    disabled={deactivating}
                    className="px-2.5 py-1 text-xs bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50 transition-colors"
                  >
                    {deactivating ? '停用中...' : '确认停用'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmDeactivate(false)}
                    className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700 rounded-md hover:bg-slate-100 transition-colors"
                  >
                    取消
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── ConnectedAppSection ──────────────────────────────────────────────────────
// 问数配置区块：拉取所有 Tableau 连接，为每个连接渲染 ConnectedAppPanel

function ConnectedAppSection({ onToast }: { onToast: (msg: string, variant?: 'success' | 'error') => void }) {
  const [connections, setConnections] = useState<TableauConnectionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetch('/api/tableau/connections?include_inactive=false', { credentials: 'include' })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: { connections: TableauConnectionItem[] }) => {
        setConnections(data.connections || []);
      })
      .catch((e: Error) => setLoadError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mt-8">
      {/* 区块标题 */}
      <div className="flex items-center gap-2 mb-4">
        <i className="ri-key-2-line text-slate-500 text-base" />
        <h2 className="text-base font-semibold text-slate-800">问数配置 — Connected App 密钥</h2>
        <span className="ml-1 text-xs text-slate-400 font-normal">Tableau JWT 用户模拟，用于 RLS 数据权限隔离</span>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
          <span className="w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
          加载 Tableau 连接...
        </div>
      )}

      {loadError && (
        <div className="px-4 py-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg flex items-center gap-2">
          <i className="ri-error-warning-line" />
          加载 Tableau 连接失败：{loadError}
        </div>
      )}

      {!loading && !loadError && connections.length === 0 && (
        <div className="py-8 text-center text-slate-400 text-sm border border-dashed border-slate-200 rounded-lg">
          <i className="ri-bar-chart-2-line text-3xl block mb-2 text-slate-200" />
          暂无激活的 Tableau 连接。请先在「Tableau 连接」页面添加连接。
        </div>
      )}

      {!loading && connections.length > 0 && (
        <div className="space-y-2">
          {connections.map((conn) => (
            <ConnectedAppPanel key={conn.id} connection={conn} onToast={onToast} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── McpConfigsPage ──────────────────────────────────────────────────────────

export default function McpConfigsPage() {
  const { isAdmin } = useAuth();

  const [servers, setServers] = useState<McpServerItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Toast 提示（T-09 Connected App 操作反馈）
  const [toastMsg, setToastMsg] = useState('');
  const [toastVariant, setToastVariant] = useState<'success' | 'error'>('success');

  const showToast = (msg: string, variant: 'success' | 'error' = 'success') => {
    setToastMsg(msg);
    setToastVariant(variant);
    setTimeout(() => setToastMsg(''), 3000);
  };

  // 表单相关
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<McpServerForm>(defaultForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // AI 解析相关
  const [pasteText, setPasteText] = useState('');
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsed, setParsed] = useState(false);

  // 连接测试
  const [testingId, setTestingId] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<Record<number, TestResult>>({});
  const [formTesting, setFormTesting] = useState(false);
  const [formTestResult, setFormTestResult] = useState<TestResult | null>(null);

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<McpServerItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadServers = useCallback(() => {
    setLoading(true);
    setError(null);
    apiList()
      .then(setServers)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadServers();
  }, [loadServers]);

  // 仅 admin 可见
  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <i className="ri-lock-line text-5xl text-slate-300 mb-4 block" />
          <h2 className="text-xl font-semibold text-slate-700 mb-2">无权限访问</h2>
          <p className="text-slate-500">仅管理员可管理 MCP 配置</p>
        </div>
      </div>
    );
  }

  const resetParseState = () => {
    setPasteText('');
    setParsed(false);
    setParseError(null);
  };

  const handleClose = () => {
    setShowForm(false);
    setFormTestResult(null);
    setFormTesting(false);
    setFormError(null);
    resetParseState();
  };

  const handleOpenNew = () => {
    setEditingId(null);
    setForm(defaultForm);
    setFormError(null);
    setFormTestResult(null);
    resetParseState();
    setShowForm(true);
  };

  const handleOpenEdit = (server: McpServerItem) => {
    setEditingId(server.id);
    setForm({
      name: server.name,
      type: server.type,
      server_url: server.server_url,
      description: server.description ?? '',
      is_active: server.is_active,
      credentials: server.credentials ?? {},
    });
    setFormError(null);
    setFormTestResult(null);
    resetParseState();
    setShowForm(true);
  };

  const handleParse = async () => {
    setParsing(true);
    setParseError(null);
    try {
      const res = await fetch('/api/mcp-configs/parse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ text: pasteText }),
      });
      const data = await res.json();
      if (data.error) {
        setParseError(data.error);
        return;
      }
      setForm({
        name: data.name ?? '',
        type: data.type ?? 'tableau',
        server_url: data.server_url ?? '',
        description: data.description ?? '',
        is_active: true,
        credentials: data.credentials ?? {},
      });
      setParsed(true);
    } catch {
      setParseError('请求失败，请检查网络或重试');
    } finally {
      setParsing(false);
    }
  };

  const handleSave = async () => {
    setFormError(null);
    setSaving(true);
    try {
      const payload: McpServerForm = {
        ...form,
        description: form.description || '',
        credentials: form.credentials,
      };
      if (editingId !== null) {
        await apiUpdate(editingId, { ...payload, description: payload.description || undefined });
      } else {
        await apiCreate(payload);
      }
      handleClose();
      loadServers();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  // 列表行内 toggle is_active
  const handleToggleActive = async (server: McpServerItem) => {
    try {
      const updated = await apiUpdate(server.id, { is_active: !server.is_active });
      setServers(prev => prev.map(s => s.id === server.id ? updated : s));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // 列表行内测试
  const handleTestInline = async (server: McpServerItem) => {
    setTestingId(server.id);
    try {
      const result = await apiTest(server.id);
      setTestResults(prev => ({ ...prev, [server.id]: result }));
    } catch (e: unknown) {
      setTestResults(prev => ({
        ...prev,
        [server.id]: { status: 'offline', latency_ms: 0, error: e instanceof Error ? e.message : String(e) },
      }));
    } finally {
      setTestingId(null);
    }
  };

  // 表单内测试连接
  const handleFormTest = async () => {
    if (editingId === null) {
      alert('请先保存后再测试');
      return;
    }
    setFormTesting(true);
    setFormTestResult(null);
    try {
      const result = await apiTest(editingId);
      setFormTestResult(result);
    } catch (e: unknown) {
      setFormTestResult({
        status: 'offline',
        latency_ms: 0,
        error: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setFormTesting(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await apiDelete(deleteTarget.id);
      setDeleteTarget(null);
      loadServers();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  };

  const truncateUrl = (url: string, max = 50) =>
    url.length > max ? url.slice(0, max) + '…' : url;

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
                <i className="ri-plug-line text-slate-500 text-base" />
              )}
              <h1 className="text-lg font-semibold text-slate-800">
                {showForm
                  ? (editingId !== null ? '编辑 MCP 配置' : '新增 MCP 配置')
                  : 'MCP 配置管理'}
              </h1>
            </div>
            <p className="text-[13px] text-slate-400 ml-6">
              {showForm
                ? '填写完成后点击右下角「保存」，或点击左侧箭头返回列表'
                : '统一管理 Tableau、StarRocks MCP 服务器连接与认证'}
            </p>
          </div>
          {!showForm && (
            <button
              onClick={handleOpenNew}
              className="flex items-center gap-1.5 px-4 py-2 bg-slate-900 text-white text-sm
                         rounded-lg hover:bg-slate-800 transition-colors"
            >
              <i className="ri-add-line" />
              新增配置
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-7xl mx-auto px-8 py-7">
        {/* ── 列表视图 ──────────────────────────────────────────────── */}
        {!showForm && (
          <>
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
            {!loading && servers.length === 0 && (
              <div className="text-center py-16">
                <i className="ri-plug-line text-5xl text-slate-200 mb-4 block" />
                <p className="text-slate-500 mb-4">暂无 MCP 配置</p>
                <button
                  onClick={handleOpenNew}
                  className="px-4 py-2 bg-slate-900 text-white text-sm rounded-lg hover:bg-slate-800 transition-colors"
                >
                  添加第一个配置
                </button>
              </div>
            )}

            {/* 配置列表 */}
            {!loading && servers.length > 0 && (
              <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50 border-b border-slate-200">
                      <th className="px-4 py-3 text-left font-medium text-slate-600">类型</th>
                      <th className="px-4 py-3 text-left font-medium text-slate-600">名称</th>
                      <th className="px-4 py-3 text-left font-medium text-slate-600">Server URL</th>
                      <th className="px-4 py-3 text-center font-medium text-slate-600">状态</th>
                      <th className="px-4 py-3 text-left font-medium text-slate-600">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {servers.map((server) => {
                      const testResult = testResults[server.id];
                      return (
                        <tr key={server.id} className="border-b border-slate-100 hover:bg-slate-50 transition-colors align-middle">
                          <td className="px-4 py-3 align-middle">
                            <TypeBadge type={server.type} />
                          </td>
                          <td className="px-4 py-3 align-middle text-slate-700 font-medium">{server.name}</td>
                          <td className="px-4 py-3 align-middle">
                            <span
                              className="font-mono text-xs text-slate-500"
                              title={server.server_url}
                            >
                              {truncateUrl(server.server_url)}
                            </span>
                          </td>
                          <td className="px-4 py-3 align-middle text-center">
                            {/* is_active toggle */}
                            <button
                              onClick={() => handleToggleActive(server)}
                              className="relative inline-flex items-center cursor-pointer"
                              title={server.is_active ? '点击禁用' : '点击启用'}
                            >
                              <div
                                className={`w-8 h-4 rounded-full transition-colors ${
                                  server.is_active ? 'bg-emerald-500' : 'bg-slate-200'
                                }`}
                              >
                                <div
                                  className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full shadow-sm transition-transform ${
                                    server.is_active ? 'translate-x-4' : ''
                                  }`}
                                />
                              </div>
                            </button>
                          </td>
                          <td className="px-4 py-3 align-middle">
                            <div className="flex items-center justify-start gap-1">
                              {/* 编辑 */}
                              <button
                                onClick={() => handleOpenEdit(server)}
                                className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700
                                           hover:bg-slate-100 rounded-md transition-colors"
                              >
                                <i className="ri-pencil-line mr-1" />
                                编辑
                              </button>
                              {/* 测试 */}
                              <button
                                onClick={() => handleTestInline(server)}
                                disabled={testingId === server.id}
                                className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700
                                           hover:bg-slate-100 rounded-md transition-colors disabled:opacity-50"
                              >
                                <i className={`mr-1 text-xs ${testingId === server.id ? 'ri-loader-4-line animate-spin' : 'ri-wifi-line'}`} />
                                {testingId === server.id
                                  ? '测试中'
                                  : testResult
                                    ? testResult.status === 'online'
                                      ? `${testResult.latency_ms}ms`
                                      : `离线`
                                    : '测试'}
                              </button>
                              {/* 删除 */}
                              <button
                                onClick={() => setDeleteTarget(server)}
                                className="px-2.5 py-1 text-xs text-red-500 hover:text-red-700
                                           hover:bg-red-50 rounded-md transition-colors"
                              >
                                <i className="ri-delete-bin-line mr-1" />
                                删除
                              </button>
                            </div>
                            {/* 测试结果详情（行内） */}
                            {testResult && (
                              <div className={`mt-1 text-xs px-2 py-0.5 rounded text-left ${
                                testResult.status === 'online'
                                  ? 'text-emerald-600'
                                  : 'text-red-500'
                              }`}>
                                {testResult.status === 'online'
                                  ? `连接正常 · ${testResult.latency_ms}ms`
                                  : `无法连接: ${testResult.error ?? '连接失败'}`}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* ── T-09: 问数配置 — Connected App 密钥 ─────────────── */}
            <ConnectedAppSection onToast={showToast} />
          </>
        )}

        {/* ── 内嵌表单视图 ──────────────────────────────────────────── */}
        {showForm && (
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
            <div className="px-6 py-4 space-y-0">
              {formError && (
                <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
                  {formError}
                </div>
              )}

              {/* 粘贴配置区 */}
              <div className="border-t border-slate-100 pt-4 mt-4 mb-0">
                <div className="mb-6">
                  <label className="block text-sm font-medium text-slate-700 mb-1">
                    粘贴配置
                    <span className="ml-2 text-xs font-normal text-slate-400">支持 JSON、.env、README 片段或自然语言描述</span>
                  </label>
                  <textarea
                    rows={5}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm font-mono focus:outline-none focus:border-blue-500 resize-none"
                    placeholder={'{\n  "mcpServers": {\n    "tableau": { ... }\n  }\n}'}
                    value={pasteText}
                    onChange={(e) => { setPasteText(e.target.value); setParsed(false); setParseError(null); }}
                  />
                  {parseError && <p className="mt-1 text-xs text-red-500">{parseError}</p>}
                  <div className="mt-2 flex items-center gap-3">
                    <button
                      type="button"
                      disabled={!pasteText.trim() || parsing}
                      onClick={handleParse}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-slate-900 text-white rounded-lg hover:bg-slate-700 disabled:opacity-40 transition-colors"
                    >
                      {parsing
                        ? <><span className="w-3 h-3 border border-white border-t-transparent rounded-full animate-spin" /><span>解析中...</span></>
                        : <><i className="ri-sparkling-line" /><span>AI 解析</span></>}
                    </button>
                    {parsed && (
                      <span className="text-xs text-green-600 flex items-center gap-1">
                        <i className="ri-checkbox-circle-line" />解析成功，请确认后保存
                      </span>
                    )}
                  </div>
                </div>

                {(parsed || pasteText) && <hr className="border-slate-100 mb-6" />}
              </div>

              {/* 基本信息 */}
              <div className="pt-0 mt-0">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
                  基本信息
                </p>

                {/* 名称 */}
                <div className="mb-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">
                    名称 <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={form.name}
                    readOnly={parsed}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="Tableau Dev"
                    className={`w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none ${parsed ? 'bg-slate-50 text-slate-600 cursor-default' : 'focus:border-blue-500'}`}
                  />
                </div>

                {/* 类型 */}
                <div className="mb-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">类型</label>
                  <select
                    value={form.type}
                    disabled={parsed}
                    onChange={(e) => setForm({ ...form, type: e.target.value, server_url: '', credentials: {} })}
                    className={`w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none ${parsed ? 'bg-slate-50 text-slate-600 cursor-default' : 'focus:border-blue-500'}`}
                  >
                    <option value="tableau">Tableau</option>
                    <option value="starrocks">StarRocks</option>
                  </select>
                </div>

                {/* Server URL */}
                <div className="mb-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">
                    Server URL <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={form.server_url}
                    readOnly={parsed}
                    onChange={(e) => setForm({ ...form, server_url: e.target.value })}
                    placeholder={URL_PLACEHOLDERS[form.type] ?? 'http://...'}
                    className={`w-full px-3 py-2 border border-slate-200 rounded-lg text-sm font-mono focus:outline-none ${parsed ? 'bg-slate-50 text-slate-600 cursor-default' : 'focus:border-blue-500'}`}
                  />
                </div>

                {/* 凭证字段 — Tableau */}
                {form.type === 'tableau' && (
                  <CredentialSection title="Tableau 认证">
                    <CredentialField
                      label="Tableau Server URL"
                      fieldKey="tableau_server"
                      placeholder="https://online.tableau.com"
                      form={form}
                      setForm={setForm}
                      readOnly={parsed}
                    />
                    <CredentialField
                      label="Site Name"
                      fieldKey="site_name"
                      placeholder="留空表示默认站点"
                      form={form}
                      setForm={setForm}
                      readOnly={parsed}
                    />
                    <CredentialField
                      label="PAT 名称"
                      fieldKey="pat_name"
                      placeholder="Personal Access Token 名称"
                      form={form}
                      setForm={setForm}
                      readOnly={parsed}
                    />
                    <CredentialField
                      label="PAT 密钥"
                      fieldKey="pat_value"
                      placeholder="Personal Access Token 密钥"
                      sensitive
                      form={form}
                      setForm={setForm}
                      readOnly={parsed}
                    />
                  </CredentialSection>
                )}

                {/* 凭证字段 — StarRocks */}
                {form.type === 'starrocks' && (
                  <CredentialSection title="StarRocks 连接">
                    <CredentialField
                      label="Host"
                      fieldKey="host"
                      placeholder="localhost"
                      form={form}
                      setForm={setForm}
                      readOnly={parsed}
                    />
                    <CredentialField
                      label="Port"
                      fieldKey="port"
                      placeholder="9030"
                      form={form}
                      setForm={setForm}
                      readOnly={parsed}
                    />
                    <CredentialField
                      label="用户名"
                      fieldKey="user"
                      placeholder="root"
                      form={form}
                      setForm={setForm}
                      readOnly={parsed}
                    />
                    <CredentialField
                      label="密码"
                      fieldKey="password"
                      placeholder=""
                      sensitive
                      form={form}
                      setForm={setForm}
                      readOnly={parsed}
                    />
                    <CredentialField
                      label="默认数据库（可选）"
                      fieldKey="database"
                      placeholder="可选"
                      form={form}
                      setForm={setForm}
                      readOnly={parsed}
                    />
                  </CredentialSection>
                )}

                {/* 描述 */}
                <div className="mb-4">
                  <label className="block text-sm font-medium text-slate-700 mb-1">描述（可选）</label>
                  <textarea
                    value={form.description}
                    readOnly={parsed}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    placeholder="关于此 MCP 服务器的简短说明"
                    rows={2}
                    className={`w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none resize-none ${parsed ? 'bg-slate-50 text-slate-600 cursor-default' : 'focus:border-blue-500'}`}
                  />
                </div>

                {/* is_active toggle */}
                <div className="mb-2">
                  <label className="flex items-center justify-between py-1 cursor-pointer">
                    <span className="text-sm text-slate-700">启用此配置</span>
                    <div
                      className={`relative w-8 h-4 rounded-full transition-colors ${
                        form.is_active ? 'bg-emerald-500' : 'bg-slate-200'
                      }`}
                      onClick={() => setForm(f => ({ ...f, is_active: !f.is_active }))}
                    >
                      <div className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full shadow-sm transition-transform ${
                        form.is_active ? 'translate-x-4' : ''
                      }`} />
                    </div>
                  </label>
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between pt-4 border-t border-slate-100 mt-4 px-6 pb-5">
              {/* 左端：测试连接 */}
              <div className="flex flex-col items-start gap-2">
                <button
                  onClick={handleFormTest}
                  disabled={formTesting}
                  title={editingId === null ? '请先保存后再测试' : undefined}
                  className={`px-3 py-1.5 text-xs border rounded-lg transition-colors flex items-center gap-1.5 ${
                    formTestResult?.status === 'online'
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                      : formTestResult?.status === 'offline'
                        ? 'border-red-200 bg-red-50 text-red-600'
                        : 'border-slate-200 text-slate-500 hover:bg-slate-50'
                  } disabled:opacity-40 disabled:cursor-not-allowed`}
                >
                  <i className={`text-xs ${
                    formTesting ? 'ri-loader-4-line animate-spin' :
                    formTestResult?.status === 'online' ? 'ri-check-line' :
                    formTestResult?.status === 'offline' ? 'ri-close-circle-line' :
                    'ri-wifi-line'
                  }`} />
                  {formTesting
                    ? '测试中...'
                    : formTestResult?.status === 'online'
                      ? `连接正常 · ${formTestResult.latency_ms}ms`
                      : formTestResult?.status === 'offline'
                        ? '连接失败'
                        : editingId !== null
                          ? '测试连接'
                          : '请先保存后再测试'}
                </button>
                {formTestResult?.status === 'offline' && formTestResult.error && (
                  <p className="text-xs px-2 py-1 rounded text-red-600 bg-red-50">
                    {formTestResult.error}
                  </p>
                )}
              </div>

              {/* 右端：取消 + 保存 */}
              <div className="flex gap-2">
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
      </div>

      {/* 删除确认弹窗 */}
      <ConfirmModal
        open={!!deleteTarget}
        title="删除 MCP 配置"
        message={`确定删除配置「${deleteTarget?.name ?? ''}」吗？此操作不可撤销。`}
        confirmLabel="删除"
        variant="danger"
        loading={deleting}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* Toast 提示（T-09 Connected App 操作反馈） */}
      {toastMsg && (
        <div
          className={`fixed bottom-6 right-6 text-white text-sm px-4 py-2.5 rounded-lg z-50 flex items-center gap-2 shadow-lg ${
            toastVariant === 'error' ? 'bg-red-600' : 'bg-slate-800'
          }`}
        >
          <i className={toastVariant === 'error' ? 'ri-error-warning-line' : 'ri-checkbox-circle-line'} />
          {toastMsg}
        </div>
      )}
    </div>
  );
}
