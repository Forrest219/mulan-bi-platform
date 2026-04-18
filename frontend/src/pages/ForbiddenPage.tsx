import { useNavigate } from 'react-router-dom';

export default function ForbiddenPage() {
  const navigate = useNavigate();
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-slate-50 text-slate-700">
      <div className="text-6xl font-bold text-slate-300 mb-4">403</div>
      <h1 className="text-2xl font-semibold mb-2">权限不足</h1>
      <p className="text-slate-500 mb-8">您没有权限访问此页面，请联系管理员。</p>
      <button
        onClick={() => navigate(-1)}
        className="px-6 py-2.5 bg-blue-700 hover:bg-blue-800 text-white rounded-lg text-sm font-medium transition-colors"
      >
        返回上一页
      </button>
    </div>
  );
}
