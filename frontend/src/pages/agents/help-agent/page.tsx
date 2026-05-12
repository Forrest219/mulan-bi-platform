import HelpAgentDrawer from './HelpAgentDrawer';

export default function HelpAgentPage() {
  return (
    <div className="min-h-screen bg-slate-50">
      <div className="bg-white border-b border-slate-200 px-8 py-5">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-2 mb-0.5">
            <i className="ri-question-answer-line text-slate-500 text-base" />
            <h1 className="text-lg font-semibold text-slate-800">Help Agent</h1>
          </div>
          <p className="text-[13px] text-slate-400 ml-7">排查 Agent、任务、连接与技能运行问题</p>
        </div>
      </div>

      <div className="px-8 py-7">
        <div className="max-w-5xl mx-auto">
          <HelpAgentDrawer open onClose={() => undefined} embedded entryPoint="route_page" />
        </div>
      </div>
    </div>
  );
}
