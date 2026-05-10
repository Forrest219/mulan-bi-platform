/**
 * OpsWorkbench — 运维工作台外壳（Phase 2 T2）
 *
 * idle/result 状态切换容器。
 *
 * B25: 响应式降级（窄屏全屏、超窄屏警告）
 */
import { useState, useEffect } from 'react';

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
  bottomBar?: React.ReactNode;
}

function OpsWorkbenchInner({
  idleContent,
  resultContent,
  submittingContent,
  homeState,
  bottomBar,
}: OpsWorkbenchInnerProps) {
  const isNarrow = useMediaQuery('(max-width: 767px)');
  const isIdle = homeState === 'HOME_IDLE';

  let content: React.ReactNode;
  if (homeState === 'HOME_SUBMITTING' && submittingContent) {
    content = submittingContent;
  } else if (homeState === 'HOME_RESULT' && resultContent) {
    content = resultContent;
  } else {
    content = idleContent;
  }

  return (
    <div className="flex flex-col h-full bg-white">
      {/* 可滚动内容区 */}
      <main
        className={[
          'flex-1 overflow-y-auto w-full',
          isIdle ? 'flex flex-col items-center pt-[8vh]' : '',
        ].join(' ')}
      >
        <div
          className={[
            'w-full max-w-4xl mx-auto px-6 pb-6',
            isIdle ? 'space-y-8' : 'pt-6 space-y-6',
          ].join(' ')}
        >
          {content}
        </div>
      </main>

      {/* 固定底部：AskBar */}
      {bottomBar && (
        <div className="shrink-0 border-t border-slate-100 bg-white px-6 py-4">
          <div className="w-full max-w-4xl mx-auto">
            {bottomBar}
          </div>
        </div>
      )}

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
    return (
      <div className="flex flex-col h-full">
        <div className="flex-1 overflow-y-auto">{props.idleContent}</div>
        {props.bottomBar && (
          <div className="shrink-0 border-t border-slate-100 bg-white px-6 py-4">
            <div className="w-full max-w-4xl mx-auto">{props.bottomBar}</div>
          </div>
        )}
      </div>
    );
  }

  return <OpsWorkbenchInner {...props} />;
}
