export default function AdminTasksPage() {
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="text-center max-w-md">
        <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-slate-100 flex items-center justify-center">
          <i className="ri-task-line text-3xl text-slate-400" />
        </div>
        <h1 className="text-xl font-bold text-slate-700 mb-2">日志与任务</h1>
        <p className="text-sm text-slate-500 leading-relaxed mb-6">
          集中管理平台运行日志与定时任务，保障平台可观测性。
        </p>
        <div className="px-4 py-3 bg-amber-50 text-amber-700 text-xs rounded-lg border border-amber-200">
          功能开发中，敬请期待
        </div>
      </div>
    </div>
  );
}
