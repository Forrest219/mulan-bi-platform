import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

export default function HomePage() {
  const [input, setInput] = useState('');
  const navigate = useNavigate();
  const { user, isAdmin, hasPermission } = useAuth();

  const handleSend = () => {
    if (!input.trim()) return;
    // TODO: AI 搜索功能开发中
    alert('功能开发中');
  };

  // Get greeting based on time of day
  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return '☀️ 早上好';
    if (hour < 18) return '🌤️ 下午好';
    return '🌙 晚上好';
  };

  // Feature icons based on user role/permissions
  const features = [
    { icon: 'ri-database-2-line', label: '数据库', path: '/database-monitor', show: hasPermission('database_monitor') || isAdmin },
    { icon: 'ri-shield-check-line', label: 'DDL检查', path: '/ddl-validator', show: hasPermission('ddl_check') || isAdmin },
    { icon: 'ri-settings-line', label: '规则配置', path: '/rule-config', show: hasPermission('rule_config') || isAdmin },
    { icon: 'ri-user-settings-line', label: '用户管理', path: '/admin/users', show: isAdmin },
    { icon: 'ri-group-line', label: '用户组', path: '/admin/groups', show: isAdmin },
  ].filter(f => f.show);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-slate-100 to-blue-50">
      <div className="max-w-4xl mx-auto px-8 pt-16">
        {/* Welcome */}
        <div className="text-center mb-6">
          <h1 className="text-4xl font-bold text-slate-600">
            {getGreeting()}，{user?.display_name || '访客'}
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
            className="absolute right-3 top-1/2 -translate-y-1/2 p-2.5 bg-blue-500 hover:bg-blue-600 text-white rounded-full transition-colors"
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
