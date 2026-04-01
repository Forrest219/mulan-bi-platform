import { useParams } from 'react-router-dom';

const knowledgeContent: Record<string, { title: string; desc: string }> = {
  metrics: {
    title: '指标字典',
    desc: '统一沉淀指标定义、计算口径与业务解释，降低口径理解成本。',
  },
  handbook: {
    title: '品控手册',
    desc: '沉淀 BI 场景下的 how-to、方法论与操作规范，形成可复用的实践知识库。',
  },
  systems: {
    title: '业务系统信息',
    desc: '维护业务系统背景、上下游关系与核心说明，补齐业务语境。',
  },
};

export default function KnowledgePage() {
  const { sub } = useParams<{ sub: string }>();
  const content = knowledgeContent[sub || ''] || {
    title: '知识库',
    desc: '知识库模块正在规划中...',
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="text-center max-w-md">
        <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-slate-100 flex items-center justify-center">
          <i className="ri-book-2-line text-3xl text-slate-400" />
        </div>
        <h1 className="text-xl font-bold text-slate-700 mb-2">{content.title}</h1>
        <p className="text-sm text-slate-500 leading-relaxed">{content.desc}</p>
        <div className="mt-6 px-4 py-3 bg-amber-50 text-amber-700 text-xs rounded-lg border border-amber-200">
          功能开发中，敬请期待
        </div>
      </div>
    </div>
  );
}
