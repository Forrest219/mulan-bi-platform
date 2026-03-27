import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

export default function HomePage() {
  const [input, setInput] = useState('');
  const navigate = useNavigate();
  const { user, isAdmin, hasPermission } = useAuth();

  const handleSend = () => {
    if (!input.trim()) return;
    console.log('Query:', input);
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
      <div className="max-w-2xl mx-auto px-6 pt-20">
        {/* Welcome */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-slate-800 mb-1">{getGreeting()}</h1>
          <p className="text-sm text-slate-500">{user?.display_name || '访客'}</p>
        </div>

        {/* Search Input */}
        <div className="relative mb-8">
          <div className="absolute inset-0 bg-white rounded-2xl shadow-lg shadow-slate-200/80" />
          <div className="relative flex items-center">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="Ask your data anything..."
              className="w-full px-7 py-5 pr-24 bg-transparent rounded-2xl text-slate-800 placeholder-slate-400 focus:outline-none text-base"
              style={{ border: '1.5px solid rgba(0,0,0,0.08)' }}
            />
            <button
              onClick={handleSend}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-3 bg-gradient-to-br from-blue-600 to-blue-500 hover:from-blue-500 hover:to-blue-400 text-white rounded-xl transition-all shadow-lg shadow-blue-500/30"
            >
              <i className="ri-send-plane-fill text-lg" />
            </button>
          </div>
        </div>

        {/* Example Prompts */}
        <div className="flex flex-wrap justify-center gap-2 mb-12">
          {[
            '最近7天表结构变化',
            '找出没有主键的表',
            '生成月度报告',
          ].map((prompt, i) => (
            <button
              key={i}
              onClick={() => setInput(prompt)}
              className="text-xs px-4 py-1.5 bg-white hover:bg-slate-50 text-slate-500 rounded-full transition-colors shadow-sm"
            >
              {prompt}
            </button>
          ))}
        </div>

        {/* Feature Icons */}
        <div className="flex justify-center gap-6">
          {features.map((feature) => (
            <button
              key={feature.label}
              onClick={() => navigate(feature.path)}
              className="flex flex-col items-center gap-2 group"
            >
              <div className="w-14 h-14 rounded-2xl bg-white shadow-md shadow-slate-200/60 flex items-center justify-center group-hover:shadow-lg group-hover:-translate-y-1 transition-all">
                <i className={`${feature.icon} text-2xl text-slate-600 group-hover:text-blue-600`} />
              </div>
              <span className="text-xs text-slate-500 group-hover:text-slate-700">{feature.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
