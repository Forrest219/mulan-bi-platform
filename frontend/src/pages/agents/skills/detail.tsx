import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../../context/AuthContext';
import {
  getSkill, patchSkill, publishVersion, rollbackVersion, getVersionDiff,
  type SkillDetail, type SkillVersion, type SchemaDiff, type PublishVersionPayload,
} from '../../../api/skills';

// ── 工具函数 ──────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const CATEGORY_OPTIONS = [
  { value: 'query', label: '查询' },
  { value: 'analysis', label: '分析' },
  { value: 'visualization', label: '可视化' },
  { value: 'reporting', label: '报告' },
  { value: 'general', label: '通用' },
];

// ── Schema Drawer ─────────────────────────────────────────────────────────────

interface SchemaDrawerProps {
  version: SkillVersion;
  activeVersion: SkillVersion | null;
  skillId: string;
  isAdmin: boolean;
  onClose: () => void;
  onRollback: (version: SkillVersion) => void;
}

function SchemaDrawer({ version, activeVersion, skillId, isAdmin, onClose, onRollback }: SchemaDrawerProps) {
  const [diff, setDiff] = useState<SchemaDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState('');

  const isActiveVersion = version.is_active;

  useEffect(() => {
    if (!isActiveVersion && activeVersion && activeVersion.id !== version.id) {
      setDiffLoading(true);
      setDiffError('');
      getVersionDiff(skillId, activeVersion.id, version.id)
        .then(d => setDiff(d))
        .catch(e => setDiffError(e instanceof Error ? e.message : '获取差异失败'))
        .finally(() => setDiffLoading(false));
    }
  }, [isActiveVersion, activeVersion, skillId, version.id]);

  const opColor = (op: string) => {
    if (op === 'add') return 'bg-emerald-50 text-emerald-800 border-l-2 border-emerald-400';
    if (op === 'remove') return 'bg-red-50 text-red-800 border-l-2 border-red-400';
    return 'bg-amber-50 text-amber-800 border-l-2 border-amber-400';
  };

  const opLabel = (op: string) => {
    if (op === 'add') return '新增';
    if (op === 'remove') return '删除';
    return '修改';
  };

  return (
    <>
      {/* 遮罩 */}
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      {/* 抽屉 */}
      <div className="fixed right-0 top-0 h-full w-[500px] bg-white shadow-2xl z-50 flex flex-col">
        {/* 头部 */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between shrink-0">
          <div>
            <h2 className="text-[15px] font-semibold text-slate-800">
              {version.version_number}
              {version.change_notes && (
                <span className="ml-2 text-[13px] text-slate-500 font-normal">— {version.change_notes}</span>
              )}
            </h2>
            <p className="text-[12px] text-slate-400 mt-0.5">{formatDate(version.created_at)}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 p-1">
            <i className="ri-close-line text-lg" />
          </button>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* LLM 描述 */}
          <div>
            <label className="block text-[12px] font-semibold text-slate-600 mb-2">
              LLM 工具描述（注入 System Prompt）
            </label>
            <textarea
              readOnly
              value={version.description}
              rows={4}
              className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg bg-slate-50 resize-none focus:outline-none font-mono"
            />
          </div>

          {/* Input Schema */}
          <div>
            <label className="block text-[12px] font-semibold text-slate-600 mb-2">Input Schema</label>
            <pre className="bg-slate-50 text-[12px] overflow-auto p-4 rounded-lg font-mono max-h-64 border border-slate-200">
              {JSON.stringify(version.input_schema, null, 2)}
            </pre>
          </div>

          {/* 代码引用 */}
          {version.code_ref && (
            <div>
              <label className="block text-[12px] font-semibold text-slate-600 mb-1">代码引用</label>
              <span className="inline-block bg-slate-100 text-slate-600 text-[12px] px-2 py-0.5 rounded font-mono">
                {version.code_ref}
              </span>
            </div>
          )}

          {/* 创建信息 */}
          <div className="flex items-center gap-4 text-[12px] text-slate-500">
            <span>创建人：{version.created_by_name ?? '—'}</span>
            <span>接入类型：{version.endpoint_type}</span>
          </div>

          {/* Diff（非活跃版本）*/}
          {!isActiveVersion && activeVersion && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <i className="ri-git-diff-line text-slate-400" />
                <span className="text-[12px] font-semibold text-slate-600">
                  与当前活跃版本（{activeVersion.version_number}）的差异
                </span>
              </div>
              {diffLoading && (
                <div className="text-center py-4 text-[12px] text-slate-400">
                  <i className="ri-loader-4-line animate-spin mr-1" />加载差异...
                </div>
              )}
              {diffError && (
                <div className="px-3 py-2 bg-red-50 text-red-700 text-[12px] rounded border border-red-200">
                  {diffError}
                </div>
              )}
              {diff && (
                <div className="space-y-2">
                  {diff.description_changed && (
                    <div className="px-3 py-2 bg-amber-50 text-amber-800 text-[12px] rounded border-l-2 border-amber-400">
                      <span className="font-medium">LLM 描述已变更</span>
                    </div>
                  )}
                  {diff.schema_patch.length === 0 && !diff.description_changed && (
                    <div className="text-center py-3 text-[12px] text-slate-400">无 Schema 差异</div>
                  )}
                  {diff.schema_patch.map((patch, i) => (
                    <div key={i} className={`px-3 py-2 rounded text-[12px] font-mono ${opColor(patch.op)}`}>
                      <span className="font-semibold mr-2">[{opLabel(patch.op)}]</span>
                      <span>{patch.path}</span>
                      {patch.value !== undefined && (
                        <div className="mt-1 text-[11px] opacity-70 truncate">
                          {JSON.stringify(patch.value)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 底部操作 */}
        {isAdmin && !isActiveVersion && (
          <div className="px-6 py-4 border-t border-slate-200 shrink-0">
            <button
              onClick={() => onRollback(version)}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 border border-slate-300 text-[13px] text-slate-700 rounded-lg hover:bg-slate-50"
            >
              <i className="ri-arrow-go-back-line" />
              回滚到此版本（{version.version_number}）
            </button>
          </div>
        )}
      </div>
    </>
  );
}

// ── 发布版本 Modal ─────────────────────────────────────────────────────────────

interface PublishModalProps {
  skillId: string;
  activeVersion: SkillVersion | null;
  nextVersionNumber: string;
  onClose: () => void;
  onPublished: () => void;
}

function PublishVersionModal({ skillId, activeVersion, nextVersionNumber, onClose, onPublished }: PublishModalProps) {
  const [desc, setDesc] = useState(activeVersion?.description ?? '');
  const [schemaText, setSchemaText] = useState(
    activeVersion ? JSON.stringify(activeVersion.input_schema, null, 2) : '{\n  "type": "object",\n  "properties": {},\n  "required": []\n}',
  );
  const [codeRef, setCodeRef] = useState(activeVersion?.code_ref ?? '');
  const [changeNotes, setChangeNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    if (!desc.trim()) { setError('请填写 LLM 工具描述'); return; }
    let parsedSchema: Record<string, unknown>;
    try {
      parsedSchema = JSON.parse(schemaText);
    } catch {
      setError('Input Schema 格式不正确，请输入合法 JSON');
      return;
    }
    const payload: PublishVersionPayload = {
      description: desc.trim(),
      input_schema: parsedSchema,
      endpoint_type: 'static',
      code_ref: codeRef.trim() || undefined,
      change_notes: changeNotes.trim() || undefined,
    };
    setSubmitting(true);
    setError('');
    try {
      await publishVersion(skillId, payload);
      onPublished();
    } catch (e) {
      setError(e instanceof Error ? e.message : '发布失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-2xl w-[600px] max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-slate-800">发布新版本 {nextVersionNumber}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <i className="ri-close-line text-lg" />
          </button>
        </div>
        <div className="px-6 py-5 space-y-4">
          {error && (
            <div className="px-3 py-2 bg-red-50 text-red-700 border border-red-200 rounded-lg text-[13px]">
              {error}
            </div>
          )}
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">
              LLM 工具描述（注入 System Prompt）<span className="text-red-500">*</span>
            </label>
            <textarea
              value={desc}
              onChange={e => setDesc(e.target.value)}
              rows={4}
              placeholder="描述此技能的功能，供 LLM 理解和调用..."
              className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 resize-none"
            />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-slate-600 mb-1">
              Input Schema（JSON Schema）
            </label>
            <textarea
              value={schemaText}
              onChange={e => setSchemaText(e.target.value)}
              rows={8}
              className="w-full px-3 py-2 text-[12px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 font-mono resize-none bg-slate-50"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">代码引用（可选）</label>
              <input
                value={codeRef}
                onChange={e => setCodeRef(e.target.value)}
                placeholder="如：ExecuteQueryTool"
                className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 font-mono"
              />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-slate-600 mb-1">变更说明</label>
              <input
                value={changeNotes}
                onChange={e => setChangeNotes(e.target.value)}
                placeholder="本次修改了什么..."
                className="w-full px-3 py-2 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
              />
            </div>
          </div>
        </div>
        <div className="px-6 py-4 border-t border-slate-200 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-[13px] text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50"
          >
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="px-4 py-2 text-[13px] text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            {submitting && <i className="ri-loader-4-line animate-spin" />}
            发布
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 回滚确认 Dialog ────────────────────────────────────────────────────────────

interface RollbackDialogProps {
  version: SkillVersion;
  onConfirm: () => void;
  onCancel: () => void;
  loading: boolean;
}

function RollbackDialog({ version, onConfirm, onCancel, loading }: RollbackDialogProps) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]">
      <div className="bg-white rounded-xl shadow-2xl w-[420px] p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center">
            <i className="ri-arrow-go-back-line text-amber-600 text-lg" />
          </div>
          <div>
            <h3 className="text-[15px] font-semibold text-slate-800">确认回滚</h3>
            <p className="text-[12px] text-slate-500 mt-0.5">此操作将重新激活历史版本</p>
          </div>
        </div>
        <p className="text-[13px] text-slate-700 mb-2">
          确认将活跃版本回滚至 <span className="font-semibold text-blue-600">{version.version_number}</span>？
        </p>
        {version.change_notes && (
          <p className="text-[12px] text-slate-500 mb-4 pl-2 border-l-2 border-slate-200">
            {version.change_notes}
          </p>
        )}
        <div className="flex justify-end gap-2 mt-5">
          <button
            onClick={onCancel}
            disabled={loading}
            className="px-4 py-2 text-[13px] text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="px-4 py-2 text-[13px] text-white bg-amber-600 rounded-lg hover:bg-amber-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            {loading && <i className="ri-loader-4-line animate-spin" />}
            确认回滚
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 主页面 ─────────────────────────────────────────────────────────────────────

export default function SkillDetailPage() {
  const { skillId } = useParams<{ skillId: string }>();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [skill, setSkill] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 左侧面板编辑状态
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [editCategory, setEditCategory] = useState('');
  const [savingField, setSavingField] = useState<string | null>(null);

  // 抽屉、Modal、Dialog 状态
  const [drawerVersion, setDrawerVersion] = useState<SkillVersion | null>(null);
  const [showPublishModal, setShowPublishModal] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState<SkillVersion | null>(null);
  const [rollbackLoading, setRollbackLoading] = useState(false);

  const loadSkill = useCallback(async () => {
    if (!skillId) return;
    setLoading(true);
    setError('');
    try {
      const data = await getSkill(skillId);
      setSkill(data);
      setEditName(data.name);
      setEditDesc(data.description ?? '');
      setEditCategory(data.category);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [skillId]);

  useEffect(() => { loadSkill(); }, [loadSkill]);

  const handlePatch = async (field: string, value: string | boolean) => {
    if (!skillId) return;
    setSavingField(field);
    try {
      const updated = await patchSkill(skillId, { [field]: value } as Parameters<typeof patchSkill>[1]);
      setSkill(prev => prev ? { ...prev, ...updated } : prev);
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSavingField(null);
    }
  };

  const handleToggleEnabled = async () => {
    if (!skill) return;
    await handlePatch('is_enabled', !skill.is_enabled);
  };

  const handleRollbackConfirm = async () => {
    if (!skillId || !rollbackTarget) return;
    setRollbackLoading(true);
    try {
      await rollbackVersion(skillId, rollbackTarget.id);
      setRollbackTarget(null);
      setDrawerVersion(null);
      await loadSkill();
    } catch (e) {
      setError(e instanceof Error ? e.message : '回滚失败');
    } finally {
      setRollbackLoading(false);
    }
  };

  const activeVersion = skill?.versions.find(v => v.is_active) ?? null;
  const sortedVersions = skill ? [...skill.versions].sort((a, b) => {
    const numA = parseInt(a.version_number.replace('v', ''));
    const numB = parseInt(b.version_number.replace('v', ''));
    return numB - numA;
  }) : [];

  const nextVersionNumber = activeVersion
    ? `v${parseInt(activeVersion.version_number.replace('v', '')) + 1}`
    : 'v1';

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-400 text-[13px]">
          <i className="ri-loader-4-line animate-spin mr-2" />加载中...
        </div>
      </div>
    );
  }

  if (error && !skill) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-red-500 text-[13px]">{error}</div>
      </div>
    );
  }

  if (!skill) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* 页面头部 */}
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-puzzle-2-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">{skill.name}</h1>
            <span className="text-slate-300">/</span>
            <span className="text-[13px] text-slate-500">技能详情</span>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">查看技能基本信息与版本历史</p>
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="max-w-6xl mx-auto">
          {error && (
            <div className="mb-4 px-4 py-3 bg-red-50 text-red-700 border border-red-200 rounded-lg text-[13px] flex items-center justify-between">
              <span>{error}</span>
              <button onClick={() => setError('')} className="text-red-400 hover:text-red-600">
                <i className="ri-close-line" />
              </button>
            </div>
          )}

          <div className="flex gap-6">
            {/* 左侧信息面板 */}
            <div className="w-72 shrink-0">
              <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-5">
                {/* skill_key */}
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                    技能标识
                  </label>
                  <span className="bg-slate-100 text-slate-600 text-[11px] px-2 py-0.5 rounded font-mono">
                    {skill.skill_key}
                  </span>
                </div>

                {/* 技能名称 */}
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                    技能名称
                  </label>
                  {isAdmin ? (
                    <div className="flex items-center gap-1">
                      <input
                        value={editName}
                        onChange={e => setEditName(e.target.value)}
                        onBlur={() => editName !== skill.name && handlePatch('name', editName)}
                        className="flex-1 px-2 py-1.5 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400"
                      />
                      {savingField === 'name' && (
                        <i className="ri-loader-4-line animate-spin text-slate-400 text-sm" />
                      )}
                    </div>
                  ) : (
                    <p className="text-[13px] text-slate-800 font-medium">{skill.name}</p>
                  )}
                </div>

                {/* 管理简介 */}
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                    管理简介
                  </label>
                  {isAdmin ? (
                    <textarea
                      value={editDesc}
                      onChange={e => setEditDesc(e.target.value)}
                      onBlur={() => editDesc !== (skill.description ?? '') && handlePatch('description', editDesc)}
                      rows={3}
                      placeholder="管理界面展示，不进入 LLM Prompt"
                      className="w-full px-2 py-1.5 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 resize-none"
                    />
                  ) : (
                    <p className="text-[13px] text-slate-600">{skill.description || <span className="text-slate-400">暂无简介</span>}</p>
                  )}
                </div>

                {/* 分类 */}
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                    分类
                  </label>
                  {isAdmin ? (
                    <select
                      value={editCategory}
                      onChange={e => { setEditCategory(e.target.value); handlePatch('category', e.target.value); }}
                      className="w-full px-2 py-1.5 text-[13px] border border-slate-200 rounded-lg focus:outline-none focus:border-blue-400 bg-white"
                    >
                      {CATEGORY_OPTIONS.map(o => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  ) : (
                    <p className="text-[13px] text-slate-600">
                      {CATEGORY_OPTIONS.find(o => o.value === skill.category)?.label ?? skill.category}
                    </p>
                  )}
                </div>

                {/* 启用开关 */}
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                    启用状态
                  </label>
                  <div className="flex items-center gap-3">
                    {isAdmin ? (
                      <button
                        onClick={handleToggleEnabled}
                        disabled={savingField === 'is_enabled'}
                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-50 ${
                          skill.is_enabled ? 'bg-blue-600' : 'bg-slate-200'
                        }`}
                      >
                        <span
                          className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                            skill.is_enabled ? 'translate-x-4' : 'translate-x-0.5'
                          }`}
                        />
                      </button>
                    ) : (
                      <span className={`w-3 h-3 rounded-full ${skill.is_enabled ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                    )}
                    <span className="text-[13px] text-slate-600">
                      {skill.is_enabled ? '已启用' : '已禁用'}
                    </span>
                    {savingField === 'is_enabled' && (
                      <i className="ri-loader-4-line animate-spin text-slate-400 text-sm" />
                    )}
                  </div>
                </div>

                {/* 时间信息 */}
                <div className="border-t border-slate-100 pt-4 space-y-1.5">
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-400">创建时间</span>
                    <span className="text-slate-600">{formatDate(skill.created_at)}</span>
                  </div>
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-400">最近更新</span>
                    <span className="text-slate-600">{formatDate(skill.updated_at)}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* 右侧版本 Timeline */}
            <div className="flex-1">
              <div className="bg-white border border-slate-200 rounded-xl p-6">
                <div className="flex items-center justify-between mb-5">
                  <h2 className="text-[14px] font-semibold text-slate-800 flex items-center gap-2">
                    <i className="ri-git-branch-line text-slate-400" />
                    版本历史
                    <span className="text-[12px] font-normal text-slate-400">({sortedVersions.length} 个版本)</span>
                  </h2>
                </div>

                {sortedVersions.length === 0 ? (
                  <div className="text-center py-10 text-[12px] text-slate-400">暂无版本记录</div>
                ) : (
                  <div className="relative pl-6">
                    {/* 竖线 */}
                    <div className="absolute left-1.5 top-2 bottom-2 border-l-2 border-slate-100" />

                    <div className="space-y-0">
                      {sortedVersions.map((version, index) => (
                        <VersionTimelineItem
                          key={version.id}
                          version={version}
                          isLast={index === sortedVersions.length - 1}
                          isAdmin={isAdmin}
                          onView={() => setDrawerVersion(version)}
                          onRollback={() => setRollbackTarget(version)}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* 发布新版本按钮 */}
                {isAdmin && (
                  <div className="mt-5 pt-5 border-t border-slate-100">
                    <button
                      onClick={() => setShowPublishModal(true)}
                      className="flex items-center gap-1.5 px-4 py-2 text-[13px] text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50"
                    >
                      <i className="ri-add-line" />
                      发布新版本 {nextVersionNumber}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Schema 查看抽屉 */}
      {drawerVersion && (
        <SchemaDrawer
          version={drawerVersion}
          activeVersion={activeVersion}
          skillId={skill.id}
          isAdmin={isAdmin}
          onClose={() => setDrawerVersion(null)}
          onRollback={(v) => { setDrawerVersion(null); setRollbackTarget(v); }}
        />
      )}

      {/* 发布版本 Modal */}
      {showPublishModal && (
        <PublishVersionModal
          skillId={skill.id}
          activeVersion={activeVersion}
          nextVersionNumber={nextVersionNumber}
          onClose={() => setShowPublishModal(false)}
          onPublished={() => { setShowPublishModal(false); loadSkill(); }}
        />
      )}

      {/* 回滚确认 Dialog */}
      {rollbackTarget && (
        <RollbackDialog
          version={rollbackTarget}
          onConfirm={handleRollbackConfirm}
          onCancel={() => setRollbackTarget(null)}
          loading={rollbackLoading}
        />
      )}
    </div>
  );
}

// ── Timeline 条目 ─────────────────────────────────────────────────────────────

interface VersionTimelineItemProps {
  version: SkillVersion;
  isLast: boolean;
  isAdmin: boolean;
  onView: () => void;
  onRollback: () => void;
}

function VersionTimelineItem({ version, isLast, isAdmin, onView, onRollback }: VersionTimelineItemProps) {
  return (
    <div className={`relative pb-5 ${isLast ? '' : ''}`}>
      {/* 节点圆点 */}
      <div className={`absolute -left-6 top-1 w-3 h-3 rounded-full border-2 border-white ${
        version.is_active ? 'bg-blue-500' : 'bg-slate-300'
      }`} />

      {/* 分隔线 */}
      {!isLast && (
        <div className="mb-3 pb-3 border-b border-slate-100" />
      )}

      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-[13px] font-semibold ${version.is_active ? 'text-blue-600' : 'text-slate-700'}`}>
              {version.version_number}
            </span>
            {version.is_active ? (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
                当前活跃
              </span>
            ) : (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500">
                历史
              </span>
            )}
            <span className="text-[12px] text-slate-400">{formatDate(version.created_at)}</span>
          </div>
          {version.change_notes && (
            <p className="text-[12px] text-slate-500 mt-1">{version.change_notes}</p>
          )}
          {version.created_by_name && (
            <p className="text-[11px] text-slate-400 mt-0.5">由 {version.created_by_name} 发布</p>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={onView}
            className="text-[12px] text-blue-600 hover:text-blue-500 px-2 py-1 rounded hover:bg-blue-50"
          >
            查看
          </button>
          {isAdmin && !version.is_active && (
            <button
              onClick={onRollback}
              className="text-[12px] text-slate-600 hover:text-slate-800 px-2 py-1 rounded hover:bg-slate-100"
            >
              回滚
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
