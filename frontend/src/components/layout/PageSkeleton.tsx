/**
 * 页面加载骨架屏（Spec 18 §4.3 代码分割 Suspense fallback）
 */
export default function PageSkeleton() {
  return (
    <div className="flex-1 flex flex-col gap-4 p-6 animate-pulse">
      {/* 页面标题 */}
      <div className="h-8 w-48 bg-slate-200 rounded-lg" />

      {/* 统计卡片 */}
      <div className="grid grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 bg-white border border-slate-100 rounded-xl p-4">
            <div className="h-4 w-24 bg-slate-100 rounded mb-3" />
            <div className="h-6 w-16 bg-slate-100 rounded" />
          </div>
        ))}
      </div>

      {/* 内容区 */}
      <div className="flex-1 bg-white border border-slate-100 rounded-xl p-6">
        <div className="h-5 w-32 bg-slate-100 rounded mb-6" />
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-4 bg-slate-50 rounded" style={{ width: `${90 - i * 5}%` }} />
          ))}
        </div>
      </div>
    </div>
  );
}
