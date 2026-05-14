import type { HelpAgentEntryPoint, HelpPageContext } from '../../../api/helpAgent';
import type {
  HelpAgentContextSnapshot,
  HelpPageSelection,
} from './helpAgentContext';

type HelpVisibleState = NonNullable<HelpPageContext['visible_state']>;

interface BuildHelpPageContextOptions {
  entryPoint?: HelpAgentEntryPoint;
  helpContext?: HelpAgentContextSnapshot;
  selection?: HelpPageSelection;
  visibleState?: HelpVisibleState;
  pathname?: string;
  search?: string;
}

function parseQuery(search: string): Record<string, string> {
  const query: Record<string, string> = {};
  const params = new URLSearchParams(search);
  params.forEach((value, key) => {
    if (!/token|secret|password|authorization|cookie/i.test(key)) {
      query[key] = value.slice(0, 200);
    }
  });
  return query;
}

function buildQueryRefs(query: Record<string, string>): Record<string, string> | undefined {
  const refs: Record<string, string> = {};
  for (const key of ['run_id', 'task_run_id', 'connection_id', 'skill_key', 'asset_id']) {
    const value = query[key];
    if (value) refs[key] = value;
  }
  return Object.keys(refs).length > 0 ? refs : undefined;
}

function mergeSelection(
  queryRefs: Record<string, string> | undefined,
  contextSelection?: HelpPageSelection,
  optionSelection?: HelpPageSelection
): HelpPageSelection | undefined {
  const merged: HelpPageSelection = {
    ...contextSelection,
    ...optionSelection,
    query_refs: {
      ...queryRefs,
      ...contextSelection?.query_refs,
      ...optionSelection?.query_refs,
    },
  };

  if (!merged.query_refs || Object.keys(merged.query_refs).length === 0) {
    delete merged.query_refs;
  }

  return merged.primary_entity || merged.entities?.length || merged.query_refs
    ? merged
    : undefined;
}

export function buildHelpPageContext(options: BuildHelpPageContextOptions = {}): HelpPageContext {
  const pathname = options.pathname ?? window.location.pathname;
  const query = parseQuery(options.search ?? window.location.search);
  const profile = options.helpContext?.profile;
  const selection = mergeSelection(
    buildQueryRefs(query),
    options.helpContext?.selection,
    options.selection
  );

  return {
    entry_point: options.entryPoint,
    path: pathname,
    title: document.title || pathname || '当前页面',
    page_key: profile?.page_key,
    page_title: profile?.page_title ?? document.title ?? pathname,
    page_domain: profile?.page_domain,
    query,
    selection,
    visible_state: options.visibleState,
    client_time: new Date().toISOString(),
  };
}
