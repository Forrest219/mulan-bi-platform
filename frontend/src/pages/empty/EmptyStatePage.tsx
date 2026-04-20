import { Link, useParams } from 'react-router-dom';

const FEATURE_NAMES: Record<string, string> = {
  'ddl-generator': 'DDL 生成器',
  'nl-query': '自然语言查询',
  'knowledge-base': '知识库',
  'publish-logs': '发布日志',
};

export default function EmptyStatePage() {
  const { feature } = useParams<{ feature: string }>();
  const name = (feature && FEATURE_NAMES[feature]) ?? feature ?? '功能';

  if (feature === 'publish-logs') {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-6 text-slate-400 select-none px-8">
        <i className="ri-git-branch-line text-6xl opacity-40" />
        <div className="text-center">
          <p className="text-lg font-medium text-slate-500 mb-1">发布日志</p>
          <p className="text-sm mb-4">记录每次数据集、报表和数据源的发布历史，支持回滚和审计</p>
        </div>
        <div className="w-full max-w-md border border-slate-200 rounded-xl overflow-hidden bg-white shadow-sm">
          <div className="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center gap-2 text-xs text-slate-500">
            <span className="font-medium text-slate-600">发布记录</span>
            <span className="ml-auto">即将上线</span>
          </div>
          {['数据集发布历史', '报表版本追踪', '数据源变更记录', '回滚与审计日志'].map((item) => (
            <div key={item} className="px-4 py-3 border-b border-slate-100 last:border-0 flex items-center gap-3">
              <div className="w-2 h-2 rounded-full bg-slate-200" />
              <span className="text-sm text-slate-400">{item}</span>
            </div>
          ))}
        </div>
        <Link to="/" className="text-sm text-blue-500 hover:underline">返回首页</Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-slate-400 select-none">
      <i className="ri-tools-line text-6xl opacity-40" />
      <p className="text-lg font-medium text-slate-500">{name} 开发中</p>
      <p className="text-sm">敬请期待，当前版本暂未开放此功能</p>
      <Link to="/" className="mt-2 text-sm text-blue-500 hover:underline">
        返回首页
      </Link>
    </div>
  );
}
