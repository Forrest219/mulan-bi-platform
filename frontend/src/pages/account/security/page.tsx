/**
 * 账户安全页 — 两步验证（TOTP MFA）设置
 *
 * 流程：
 *   1. 请求 /api/auth/mfa/setup 获取 QR URI + secret + backup codes
 *   2. 展示 QR 码供用户扫描
 *   3. 用户输入 authenticator App 中的 6 位验证码
 *   4. 调用 /api/auth/mfa/verify-setup 完成启用
 *   5. 展示备用恢复代码（仅此一次）
 *
 * 禁用流程：
 *   输入当前密码 + MFA 验证码 → /api/auth/mfa/disable
 */
import { useState, useEffect, useCallback } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { useAuth } from '../../../context/AuthContext';
import { API_BASE } from '../../../config';

type MfaStep = 'loading' | 'disabled' | 'scan' | 'verify' | 'recovery' | 'enabled';

interface SetupData {
  secret: string;
  qr_uri: string;
  backup_codes: string[];
}

export default function AccountSecurityPage() {
  const { user } = useAuth();
  const [step, setStep] = useState<MfaStep>('loading');
  const [setupData, setSetupData] = useState<SetupData | null>(null);
  const [verifyCode, setVerifyCode] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // 禁用 MFA 相关
  const [disablePassword, setDisablePassword] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [showDisableForm, setShowDisableForm] = useState(false);

  const checkMfaStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/mfa/status`, { credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        setStep(data.mfa_enabled ? 'enabled' : 'disabled');
      } else {
        setStep('disabled');
      }
    } catch {
      setStep('disabled');
    }
  }, []);

  useEffect(() => {
    checkMfaStatus();
  }, [checkMfaStatus]);

  // 步骤 1: 开始设置 — 获取 QR 码
  const handleStartSetup = async () => {
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/mfa/setup`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) {
        const data = await res.json();
        setError(data.detail || '获取验证码设置信息失败');
        setLoading(false);
        return;
      }
      const data: SetupData = await res.json();
      setSetupData(data);
      setStep('scan');
    } catch {
      setError('网络错误，请重试');
    }
    setLoading(false);
  };

  // 步骤 2: 验证 TOTP Code 并启用
  const handleVerifySetup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/mfa/verify-setup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ code: verifyCode }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || '验证码不正确，请重试');
        setLoading(false);
        return;
      }
      // 启用成功 — 展示恢复代码
      setBackupCodes(data.backup_codes || []);
      setStep('recovery');
    } catch {
      setError('网络错误，请重试');
    }
    setLoading(false);
  };

  // 禁用 MFA
  const handleDisableMfa = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/mfa/disable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ password: disablePassword, code: disableCode }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || '关闭两步验证失败');
        setLoading(false);
        return;
      }
      // 禁用成功
      setShowDisableForm(false);
      setDisablePassword('');
      setDisableCode('');
      setStep('disabled');
    } catch {
      setError('网络错误，请重试');
    }
    setLoading(false);
  };

  // 下载恢复代码
  const handleDownloadCodes = () => {
    const text = [
      `MulanBI 两步验证恢复代码`,
      `用户：${user?.display_name ?? user?.username ?? ''}`,
      `生成时间：${new Date().toLocaleString('zh-CN')}`,
      ``,
      `请妥善保管以下恢复代码，每个代码只能使用一次：`,
      ``,
      ...backupCodes.map((code, i) => `${i + 1}. ${code}`),
      ``,
      `注意：如果丢失所有恢复代码且无法访问验证器应用，请联系管理员重置。`,
    ].join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'mulanbi-recovery-codes.txt';
    a.click();
    URL.revokeObjectURL(url);
  };

  // 复制恢复代码
  const handleCopyCodes = () => {
    const text = backupCodes.join('\n');
    navigator.clipboard.writeText(text).catch(() => {
      // fallback: do nothing — download is always available
    });
  };

  return (
    <div className="max-w-2xl mx-auto py-8 px-4">
      <h1 className="text-lg font-semibold text-slate-900 mb-1">账户安全</h1>
      <p className="text-sm text-slate-500 mb-6">管理两步验证等安全设置</p>

      {/* 错误提示 */}
      {error && (
        <div className="mb-4 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-red-600 text-sm">
          {error}
        </div>
      )}

      {/* ── 加载中 ── */}
      {step === 'loading' && (
        <div className="text-sm text-slate-500">正在加载安全设置...</div>
      )}

      {/* ── MFA 未启用 ── */}
      {step === 'disabled' && (
        <div className="bg-white border border-slate-200 rounded-lg p-6">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center shrink-0">
              <svg className="w-5 h-5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <div className="flex-1">
              <h2 className="text-base font-semibold text-slate-900 mb-1">两步验证</h2>
              <p className="text-sm text-slate-500 mb-4">
                使用验证器应用（如 Google Authenticator、Microsoft Authenticator）生成一次性验证码，增强账户安全性。
              </p>
              <button
                onClick={handleStartSetup}
                disabled={loading}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium
                           rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? '正在生成...' : '启用两步验证'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 步骤 1: 扫描二维码 ── */}
      {step === 'scan' && setupData && (
        <div className="bg-white border border-slate-200 rounded-lg p-6">
          <h2 className="text-base font-semibold text-slate-900 mb-1">扫描二维码</h2>
          <p className="text-sm text-slate-500 mb-4">
            使用验证器应用扫描下方二维码，或手动输入密钥。
          </p>

          <div className="flex flex-col items-center gap-4 mb-6">
            <div className="p-4 bg-white border border-slate-200 rounded-xl">
              <QRCodeSVG value={setupData.qr_uri} size={200} level="M" />
            </div>
            <div className="text-center">
              <p className="text-xs text-slate-400 mb-1">无法扫描？手动输入以下密钥：</p>
              <code className="text-sm font-mono bg-slate-100 px-3 py-1 rounded select-all text-slate-700">
                {setupData.secret}
              </code>
            </div>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => { setStep('disabled'); setSetupData(null); setError(''); }}
              className="flex-1 px-4 py-2 bg-white border border-slate-300 text-slate-700
                         text-sm font-medium rounded-md hover:bg-slate-50 transition-colors"
            >
              取消
            </button>
            <button
              onClick={() => setStep('verify')}
              className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white
                         text-sm font-medium rounded-md transition-colors"
            >
              下一步
            </button>
          </div>
        </div>
      )}

      {/* ── 步骤 2: 输入验证码 ── */}
      {step === 'verify' && (
        <div className="bg-white border border-slate-200 rounded-lg p-6">
          <h2 className="text-base font-semibold text-slate-900 mb-1">输入验证码</h2>
          <p className="text-sm text-slate-500 mb-4">
            打开验证器应用，输入显示的 6 位验证码以完成设置。
          </p>

          <form onSubmit={handleVerifySetup} className="space-y-4">
            <div>
              <label htmlFor="mfa-verify-code" className="block text-sm font-medium text-slate-700 mb-1">
                验证码
              </label>
              <input
                type="text"
                id="mfa-verify-code"
                value={verifyCode}
                onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                maxLength={6}
                required
                autoFocus
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                           text-slate-900 placeholder:text-slate-400 bg-white text-center
                           tracking-widest font-mono
                           focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                           transition-colors duration-150"
                placeholder="000000"
              />
            </div>

            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => { setStep('scan'); setVerifyCode(''); setError(''); }}
                className="flex-1 px-4 py-2 bg-white border border-slate-300 text-slate-700
                           text-sm font-medium rounded-md hover:bg-slate-50 transition-colors"
              >
                返回
              </button>
              <button
                type="submit"
                disabled={loading || verifyCode.length !== 6}
                className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white
                           text-sm font-medium rounded-md transition-colors
                           disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? '验证中...' : '确认启用'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── 步骤 3: 恢复代码 ── */}
      {step === 'recovery' && (
        <div className="bg-white border border-slate-200 rounded-lg p-6">
          <div className="flex items-center gap-2 mb-1">
            <svg className="w-5 h-5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            <h2 className="text-base font-semibold text-slate-900">两步验证已启用</h2>
          </div>
          <p className="text-sm text-slate-500 mb-4">
            请保存以下恢复代码。当你无法使用验证器应用时，可以使用恢复代码登录。每个代码只能使用一次。
          </p>

          <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 mb-4">
            <div className="grid grid-cols-2 gap-2">
              {backupCodes.map((code, index) => (
                <div key={index} className="font-mono text-sm text-slate-700 bg-white px-3 py-1.5 rounded border border-slate-200 text-center">
                  {code}
                </div>
              ))}
            </div>
          </div>

          <div className="flex gap-3 mb-4">
            <button
              onClick={handleDownloadCodes}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2
                         bg-white border border-slate-300 text-slate-700
                         text-sm font-medium rounded-md hover:bg-slate-50 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              下载恢复代码
            </button>
            <button
              onClick={handleCopyCodes}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2
                         bg-white border border-slate-300 text-slate-700
                         text-sm font-medium rounded-md hover:bg-slate-50 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              复制恢复代码
            </button>
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-md px-3 py-2 text-sm text-amber-700 mb-4">
            请务必将恢复代码保存在安全的地方。关闭此页面后将无法再次查看。
          </div>

          <button
            onClick={() => setStep('enabled')}
            className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white
                       text-sm font-medium rounded-md transition-colors"
          >
            我已保存，完成设置
          </button>
        </div>
      )}

      {/* ── MFA 已启用 ── */}
      {step === 'enabled' && (
        <div className="bg-white border border-slate-200 rounded-lg p-6">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center shrink-0">
              <svg className="w-5 h-5 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div className="flex-1">
              <h2 className="text-base font-semibold text-slate-900 mb-1">两步验证已启用</h2>
              <p className="text-sm text-slate-500 mb-4">
                你的账户已受两步验证保护。登录时需要验证器应用中的验证码。
              </p>

              {!showDisableForm ? (
                <button
                  onClick={() => setShowDisableForm(true)}
                  className="px-4 py-2 bg-white border border-red-300 text-red-600
                             text-sm font-medium rounded-md hover:bg-red-50 transition-colors"
                >
                  关闭两步验证
                </button>
              ) : (
                <form onSubmit={handleDisableMfa} className="space-y-3 border-t border-slate-200 pt-4 mt-4">
                  <p className="text-sm text-slate-600">
                    关闭两步验证需要验证你的身份。请输入当前密码和验证码。
                  </p>
                  <div>
                    <label htmlFor="disable-password" className="block text-sm font-medium text-slate-700 mb-1">
                      当前密码
                    </label>
                    <input
                      type="password"
                      id="disable-password"
                      value={disablePassword}
                      onChange={(e) => setDisablePassword(e.target.value)}
                      required
                      className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                                 text-slate-900 placeholder:text-slate-400 bg-white
                                 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                                 transition-colors duration-150"
                      placeholder="请输入当前密码"
                    />
                  </div>
                  <div>
                    <label htmlFor="disable-mfa-code" className="block text-sm font-medium text-slate-700 mb-1">
                      验证码
                    </label>
                    <input
                      type="text"
                      id="disable-mfa-code"
                      value={disableCode}
                      onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      maxLength={6}
                      required
                      className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                                 text-slate-900 placeholder:text-slate-400 bg-white text-center
                                 tracking-widest font-mono
                                 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                                 transition-colors duration-150"
                      placeholder="000000"
                    />
                  </div>
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => { setShowDisableForm(false); setDisablePassword(''); setDisableCode(''); setError(''); }}
                      className="flex-1 px-4 py-2 bg-white border border-slate-300 text-slate-700
                                 text-sm font-medium rounded-md hover:bg-slate-50 transition-colors"
                    >
                      取消
                    </button>
                    <button
                      type="submit"
                      disabled={loading || !disablePassword || disableCode.length !== 6}
                      className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 text-white
                                 text-sm font-medium rounded-md transition-colors
                                 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {loading ? '处理中...' : '确认关闭'}
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
