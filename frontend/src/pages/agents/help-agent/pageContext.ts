import type { HelpAgentEntryPoint, HelpPageContext } from '../../../api/helpAgent';

type HelpSelection = NonNullable<HelpPageContext['selection']>;
type HelpVisibleState = NonNullable<HelpPageContext['visible_state']>;

interface BuildHelpPageContextOptions {
  entryPoint?: HelpAgentEntryPoint;
  selection?: HelpSelection;
  visibleState?: HelpVisibleState;
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

function numberFromQuery(query: Record<string, string>, key: string): number | undefined {
  const value = query[key];
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function buildSelectionFromQuery(query: Record<string, string>): HelpSelection {
  const selection: HelpSelection = {};
  if (query.run_id) selection.run_id = query.run_id;
  const taskRunId = numberFromQuery(query, 'task_run_id');
  if (taskRunId !== undefined) selection.task_run_id = taskRunId;
  const connectionId = numberFromQuery(query, 'connection_id');
  if (connectionId !== undefined) selection.connection_id = connectionId;
  const assetId = numberFromQuery(query, 'asset_id');
  if (assetId !== undefined) selection.asset_id = assetId;
  if (query.skill_key) selection.skill_key = query.skill_key;
  return selection;
}

function compactSelection(selection: HelpSelection): HelpSelection | undefined {
  return Object.values(selection).some((value) => value !== undefined && value !== '') ? selection : undefined;
}

export function buildHelpPageContext(options: BuildHelpPageContextOptions = {}): HelpPageContext {
  const query = parseQuery(window.location.search);
  const querySelection = buildSelectionFromQuery(query);
  const selection = compactSelection({ ...querySelection, ...options.selection });

  return {
    entry_point: options.entryPoint,
    path: window.location.pathname,
    query,
    selection,
    visible_state: options.visibleState,
    client_time: new Date().toISOString(),
  };
}
