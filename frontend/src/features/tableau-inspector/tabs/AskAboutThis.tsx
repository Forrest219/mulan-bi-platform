import { useNavigate } from 'react-router-dom';

interface AskAboutThisProps {
  assetName: string;
  assetId: string;
  healthScore: number;
}

export function AskAboutThis({ assetName, assetId, healthScore }: AskAboutThisProps) {
  const navigate = useNavigate();

  function handleAsk() {
    const question = `分析资产 ${assetName}（ID: ${assetId}）的健康度评分${healthScore}，找出主要问题并给出改进建议`;
    const encoded = encodeURIComponent(question);
    navigate(`/?prefill=${encoded}`);
  }

  return (
    <button
      onClick={handleAsk}
      className="mt-3 w-full py-2 px-4 text-sm border border-slate-200 rounded-lg hover:bg-slate-50 flex items-center justify-center gap-2 text-slate-600 transition-colors"
    >
      <i className="ri-chat-3-line" />
      针对此资产提问
    </button>
  );
}
