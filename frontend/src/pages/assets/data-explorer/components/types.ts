export type ExplorerObjectType = 'table' | 'view';

export type ExplorerTabKey = 'overview' | 'schema' | 'preview' | 'permissions';

export interface ExplorerError {
  error_code?: string;
  message: string;
  detail?: Record<string, unknown> | null;
}

export interface ExplorerConnection {
  id: number;
  name: string;
  db_type: string;
  host?: string;
  port?: number;
  database_name?: string | null;
  username?: string;
  owner_id?: number;
  is_active?: boolean;
  last_tested_at?: string | null;
  last_test_success?: boolean | null;
  explorer_supported?: boolean;
  unsupported_reason?: string | null;
  error?: ExplorerError | null;
}

export interface ExplorerSchema {
  name: string;
  table_count?: number | null;
  view_count?: number | null;
}

export interface ExplorerTable {
  schema: string;
  name: string;
  type: ExplorerObjectType;
  comment?: string | null;
  row_count?: number | null;
  row_count_estimate?: number | null;
  column_count?: number | null;
  table_ref: string;
}

export interface ExplorerSelection {
  connectionId?: number | null;
  schema?: string | null;
  tableRef?: string | null;
}

export interface TableOverview {
  resource_id?: string;
  schema: string;
  name: string;
  type: ExplorerObjectType;
  comment?: string | null;
  primary_key?: string[];
  column_count?: number | null;
  indexes_count?: number | null;
  foreign_keys_count?: number | null;
  row_count_estimate?: number | null;
  data_size_bytes?: number | null;
  index_size_bytes?: number | null;
  total_size_bytes?: number | null;
  created_at?: string | null;
  table_updated_at?: string | null;
  preview_available?: boolean;
}

export type SemanticRole = 'identifier' | 'time' | 'measure' | 'flag' | 'dimension' | string;

export interface TableColumn {
  name: string;
  data_type: string;
  nullable?: boolean;
  default?: string | null;
  comment?: string | null;
  is_primary_key?: boolean;
  is_indexed?: boolean;
  semantic_role?: SemanticRole | null;
}

export interface PreviewColumn {
  name: string;
  data_type?: string | null;
}

export type PreviewCell = string | number | boolean | null;

export interface PreviewData {
  columns: PreviewColumn[];
  rows: PreviewCell[][];
  limit?: number;
  truncated?: boolean;
}

export interface PermissionSummary {
  can_browse?: boolean;
  can_preview?: boolean;
  scope?: string;
  source?: string;
  notes?: string[];
  message?: string;
  grants?: Array<{
    label: string;
    value: string | boolean | null;
  }>;
}
