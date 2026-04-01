import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { LOGO_URL } from '../../config';

export default function HomePage() {
  const [input, setInput] = useState('');
  const [message, setMessage] = useState('');
  const navigate = useNavigate();
  const { user, isAdmin, hasPermission } = useAuth();

  const handleSend = () => {
    if (!input.trim()) return;
    setMessage('功能开发中');
  };

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return '☀️ 早上好';
    if (hour < 18) return '🌤️ 下午好';
    return '🌙 晚上好';
  };

  const features = [
    { icon: 'ri-database-2-line', label: '数据库', path: '/database-monitor', show: hasPermission('database_monitor') || isAdmin },
    { icon: 'ri-shield-check-line', label: 'DDL检查', path: '/ddl-validator', show: hasPermission('ddl_check') || isAdmin },
    { icon: 'ri-settings-line', label: '规则配置', path: '/rule-config', show: hasPermission('rule_config') || isAdmin },
    { icon: 'ri-user-settings-line', label: '用户管理', path: '/admin/users', show: isAdmin },
    { icon: 'ri-group-line', label: '用户组', path: '/admin/groups', show: isAdmin },
  ].filter(f => f.show);

  // ===== 未登录：显示简洁登录引导 ===== //
  if (!user) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50 flex items-center justify-center">
        <div className="bg-white rounded-xl border border-slate-200 p-10 w-full max-w-md text-center">
          <img
            src={LOGO_URL}
            alt="Mulan Platform Logo"
            className="w-14 h-14 object-contain mx-auto mb-4"
          />
          <h1 className="text-2xl font-bold text-slate-800 mb-2">Mulan Platform</h1>
          <p className="text-sm text-slate-400 mb-8">数据建模与治理平台</p>
          <p className="text-slate-500 mb-6">请先登录以访问平台功能</p>
          <Link
            to="/login"
            className="inline-block w-full py-2.5 bg-slate-900 text-white rounded-lg text-sm font-semibold hover:bg-slate-700 transition-colors"
          >
            登录
          </Link>
          <div className="mt-4">
            <Link to="/register" className="text-sm text-blue-600 hover:text-blue-700">
              没有账号？去注册
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // ===== 已登录：显示 AI 搜索首页 ===== //
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50">
      <div className="max-w-4xl mx-auto px-8 pt-16">
        {message && (
          <div className="mb-4 px-4 py-2 bg-amber-50 text-amber-700 border border-amber-200 rounded-lg text-sm">
            {message}
          </div>
        )}

        {/* Welcome */}
        <div className="text-center mb-6">
          <h1 className="text-4xl font-bold text-slate-600">
            {getGreeting()}，{user?.display_name}
          </h1>
        </div>

        {/* Search Input - Hero */}
        <div className="relative mb-8">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="有什么可以帮到您"
            rows={2}
            className="w-full px-8 pr-20 py-4 bg-white text-slate-800 placeholder-slate-400 focus:outline-none text-base resize-none leading-relaxed rounded-full"
            style={{ border: '1px solid #dfe1e5' }}
          />
          <button
            onClick={handleSend}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-2.5 bg-slate-900 hover:bg-slate-800 text-white rounded-full transition-colors"
          >
            <i className="ri-send-plane-fill text-base" />
          </button>
        </div>

        {/* Example Prompts */}
        <div className="flex flex-wrap justify-center gap-2 mb-8 opacity-60">
          {[
            '最近7天表结构变化',
            '找出没有主键的表',
            '生成月度报告',
          ].map((prompt, i) => (
            <button
              key={i}
              onClick={() => setInput(prompt)}
              className="text-xs px-3 py-1 hover:bg-slate-200/60 text-slate-500 rounded-full transition-colors"
            >
              {prompt}
            </button>
          ))}
        </div>

        {/* Feature Icons */}
        <div className="flex justify-center items-center gap-6">
          {features.map((feature, i) => (
            <button
              key={feature.label}
              onClick={() => navigate(feature.path)}
              className="flex flex-col items-center gap-1 group"
            >
              <div className="w-10 h-10 rounded-full bg-white/80 flex items-center justify-center group-hover:bg-white group-hover:shadow-sm transition-all">
                <i className={`${feature.icon} text-lg text-slate-400 group-hover:text-blue-500`} />
              </div>
              <span className="text-xs text-slate-400 group-hover:text-slate-600">{feature.label}</span>
            </button>
          )).flatMap((el, i, arr) =>
            i < arr.length - 1 ? [el, <span key={`sep-${i}`} className="text-slate-300 select-none">｜</span>] : [el]
          )}
        </div>
      </div>
    </div>
  );
}
