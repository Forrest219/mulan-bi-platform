/**
 * OpsWorkbench — 运维工作台外壳（Phase 2 T2）
 *
 * idle/result 状态切换容器。
 *
 * B25: 响应式降级（窄屏全屏、超窄屏警告）
 */
import { useState, useEffect } from 'react';

import { useAuth } from '../../context/AuthContext';
import { ENABLE_OPS_WORKBENCH } from '../../config';

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const m = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    m.addEventListener('change', handler);
    return () => m.removeEventListener('change', handler);
  }, [query]);

  return matches;
}

interface OpsWorkbenchInnerProps {
  idleContent: React.ReactNode;
  resultContent?: React.ReactNode;
  submittingContent?: React.ReactNode;
  homeState: 'HOME_IDLE' | 'HOME_SUBMITTING' | 'HOME_RESULT' | 'HOME_ERROR' | 'HOME_OFFLINE';
}

function OpsWorkbenchInner({
  idleContent,
  resultContent,
  submittingContent,
  homeState,
}: OpsWorkbenchInnerProps) {
  const isNarrow = useMediaQuery('(max-width: 767px)');

  let content: React.ReactNode;
  if (homeState === 'HOME_SUBMITTING' && submittingContent) {
    content = submittingContent;
  } else if (homeState === 'HOME_RESULT' && resultContent) {
    content = resultContent;
  } else {
    content = idleContent;
  }

  return (
    <div className="relative flex flex-col min-h-full bg-white">
      {/* 主内容区 */}
      <main
        className={[
          'flex-1 flex flex-col w-full',
          homeState === 'HOME_IDLE' ? 'items-center pt-[8vh]' : '',
          homeState !== 'HOME_IDLE' ? 'pb-40' : 'pb-6',
        ].join(' ')}
      >
        <div
          className={[
            'w-full max-w-4xl mx-auto px-6',
            homeState === 'HOME_IDLE' ? 'space-y-8' : 'pt-6 space-y-6',
          ].join(' ')}
        >
          {content}
        </div>
      </main>

      {/* B25: 超窄屏降级提示 */}
      {isNarrow && (
        <div className="fixed bottom-20 left-0 right-0 z-50 bg-amber-50 border-t border-amber-200 px-4 py-2 text-xs text-amber-700 text-center">
          窄屏模式下部分功能受限，建议在桌面端使用
        </div>
      )}
    </div>
  );
}

export function OpsWorkbench(props: OpsWorkbenchInnerProps) {
  if (!ENABLE_OPS_WORKBENCH) {
    return <>{props.idleContent}</>;
  }

  return <OpsWorkbenchInner {...props} />;
}
