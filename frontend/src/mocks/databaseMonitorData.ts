export interface DataSource {
  id: string;
  name: string;
  type: 'MySQL' | 'SQL Server';
  host: string;
  database: string;
  status: 'connected' | 'warning' | 'error';
  tableCount: number;
  lastScan: string;
}

export interface QualityMetric {
  datasource: string;
  table: string;
  nullRate: number;
  duplicateRate: number;
  invalidRate: number;
  score: number;
  trend: 'up' | 'down' | 'stable';
}

export const mockDataSources: DataSource[] = [
  {
    id: 'ds-001',
    name: 'prod-mysql-orders',
    type: 'MySQL',
    host: '10.20.30.11:3306',
    database: 'db_orders',
    status: 'connected',
    tableCount: 48,
    lastScan: '2026-03-25 09:12',
  },
  {
    id: 'ds-002',
    name: 'prod-mysql-users',
    type: 'MySQL',
    host: '10.20.30.12:3306',
    database: 'db_users',
    status: 'warning',
    tableCount: 22,
    lastScan: '2026-03-25 08:45',
  },
  {
    id: 'ds-003',
    name: 'dw-sqlserver-main',
    type: 'SQL Server',
    host: '10.20.30.20:1433',
    database: 'DW_MAIN',
    status: 'connected',
    tableCount: 135,
    lastScan: '2026-03-25 07:30',
  },
  {
    id: 'ds-004',
    name: 'staging-mysql-report',
    type: 'MySQL',
    host: '10.20.30.50:3306',
    database: 'db_report',
    status: 'error',
    tableCount: 0,
    lastScan: '2026-03-24 22:00',
  },
];

export const mockQualityMetrics: QualityMetric[] = [
  { datasource: 'prod-mysql-orders', table: 'order_detail', nullRate: 12.4, duplicateRate: 0.2, invalidRate: 3.1, score: 84, trend: 'down' },
  { datasource: 'prod-mysql-orders', table: 'order_main', nullRate: 0.8, duplicateRate: 0.0, invalidRate: 0.5, score: 98, trend: 'stable' },
  { datasource: 'prod-mysql-users', table: 'user_profile', nullRate: 22.1, duplicateRate: 1.4, invalidRate: 5.6, score: 71, trend: 'down' },
  { datasource: 'prod-mysql-users', table: 'user_auth', nullRate: 0.1, duplicateRate: 0.0, invalidRate: 0.2, score: 99, trend: 'up' },
  { datasource: 'dw-sqlserver-main', table: 'DIM_PRODUCT', nullRate: 5.3, duplicateRate: 0.7, invalidRate: 1.2, score: 91, trend: 'up' },
  { datasource: 'dw-sqlserver-main', table: 'FACT_SALES', nullRate: 2.1, duplicateRate: 0.1, invalidRate: 0.8, score: 96, trend: 'stable' },
];

export const monitorStats = {
  totalTables: 205,
  avgScore: 88,
  highRiskTables: 7,
  lastRunTime: '2026-03-25 09:15',
};
