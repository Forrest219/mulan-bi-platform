import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

export type HelpPageDomain =
  | 'assets'
  | 'governance'
  | 'agents'
  | 'config'
  | 'admin'
  | 'account'
  | 'home'
  | 'unknown';

export interface HelpPageProfile {
  page_key: string;
  page_title: string;
  page_domain: HelpPageDomain;
  default_questions: string[];
}

export interface HelpContextEntity {
  type: string;
  id: string;
  label?: string;
  source?: 'route' | 'query' | 'selection' | 'page-state';
}

export interface HelpPageSelection {
  primary_entity?: HelpContextEntity;
  entities?: HelpContextEntity[];
  query_refs?: Record<string, string>;
}

export interface HelpAgentContextSnapshot {
  profile: HelpPageProfile;
  selection?: HelpPageSelection;
}

interface HelpAgentContextValue extends HelpAgentContextSnapshot {
  setSelectionPatch: (selection?: HelpPageSelection) => void;
}

interface HelpAgentContextProviderProps {
  profile?: HelpPageProfile;
  children?: ReactNode;
}

export const FALLBACK_HELP_PROFILE: HelpPageProfile = {
  page_key: 'unknown',
  page_title: '当前页面',
  page_domain: 'unknown',
  default_questions: [
    '这个页面该怎么排查问题？',
    '当前页面有什么异常需要关注？',
    '我应该从哪里开始检查？',
  ],
};

const HelpAgentContext = createContext<HelpAgentContextValue | null>(null);

export function HelpAgentContextProvider({ profile, children }: HelpAgentContextProviderProps) {
  const [selectionPatch, setSelectionPatch] = useState<HelpPageSelection | undefined>();
  const resolvedProfile = profile ?? FALLBACK_HELP_PROFILE;

  useEffect(() => {
    setSelectionPatch(undefined);
  }, [resolvedProfile.page_key]);

  const setSelectionPatchStable = useCallback((selection?: HelpPageSelection) => {
    setSelectionPatch(selection);
  }, []);

  const value = useMemo<HelpAgentContextValue>(
    () => ({
      profile: resolvedProfile,
      selection: selectionPatch,
      setSelectionPatch: setSelectionPatchStable,
    }),
    [resolvedProfile, selectionPatch, setSelectionPatchStable]
  );

  return (
    <HelpAgentContext.Provider value={value}>
      {children}
    </HelpAgentContext.Provider>
  );
}

export function useHelpAgentContext(): HelpAgentContextSnapshot {
  const context = useContext(HelpAgentContext);
  return useMemo(
    () => ({
      profile: context?.profile ?? FALLBACK_HELP_PROFILE,
      selection: context?.selection,
    }),
    [context?.profile, context?.selection]
  );
}

export function useHelpAgentSelection(selection?: HelpPageSelection) {
  const context = useContext(HelpAgentContext);
  const setSelectionPatch = context?.setSelectionPatch;

  useEffect(() => {
    if (!setSelectionPatch) return;
    setSelectionPatch(selection);
    return () => setSelectionPatch(undefined);
  }, [setSelectionPatch, selection]);
}
