import { useNavigate } from 'react-router-dom';
import type { AssetHealth } from '../../../api/tableau';

interface AskAboutThisProps {
  assetName: string;
  assetId: string;
  healthScore: number;
  /** Optional: the full health checks, used to pick the top failed factor */
  checks?: AssetHealth['checks'];
}

export function AskAboutThis({ assetName, assetId, healthScore, checks }: AskAboutThisProps) {
  const navigate = useNavigate();

  function handleAsk() {
    // OI-2-B: hardcoded templates — pick the top failed factor for a contextual question
    const failedChecks = checks?.filter((c) => !c.passed) ?? [];
    const topFailed = failedChecks[0];

    // Template: 为什么这个资产的健康分是 {score}？
    const questionTemplate = topFailed
      ? `为什么「${assetName}」的健康分是 ${healthScore}？它的「${topFailed.label}」未通过，请分析这个问题并给出改进建议。`
      : `「${assetName}」的健康分是 ${healthScore}，请总结它的整体健康状况并指出最需要关注的问题。`;

    const encoded = encodeURIComponent(questionTemplate);
    // Navigate to home page with prefill question + asset luid + tab=health
    navigate(`/?prefill=${encoded}&asset=${encodeURIComponent(assetId)}&tab=health`);
  }

  return (
    <button
      onClick={handleAsk}
      className="mt-3 w-full py-2 px-4 text-xs border border-slate-200 rounded-lg hover:bg-slate-50 flex items-center justify-center gap-2 text-slate-600 transition-colors"
    >
      <i className="ri-chat-3-line" />
      针对此资产提问
    </button>
  );
}
