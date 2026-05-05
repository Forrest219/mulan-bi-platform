/**
 * 统一连接列表 API
 *
 * 合并以下来源：
 * - GET /api/datasources          → postgresql / starrocks 等数据库连接
 * - GET /api/tableau/connections → Tableau 连接
 *
 * 返回 {id, name, type} 数组，type 枚举：postgresql | tableau | starrocks
 */
import { API_BASE } from '../config';
import { listConnections as listTableauConnections } from './tableau';
import { listDataSources } from './datasources';

export type ConnectionType = 'postgresql' | 'tableau' | 'starrocks';

export interface ConnectionOption {
  id: number;
  name: string;
  type: ConnectionType;
}

/** 映射 db_type → ConnectionType */
function mapDbType(db_type: string): ConnectionType {
  switch (db_type) {
    case 'postgresql':
      return 'postgresql';
    case 'starrocks':
      return 'starrocks';
    default:
      return 'postgresql';
  }
}

export async function listConnections(): Promise<ConnectionOption[]> {
  const results: ConnectionOption[] = [];

  // 并行请求两个接口，任意一个失败不影响整体降级
  const [datasourceResult, tableauResult] = await Promise.allSettled([
    listDataSources().catch(() => null),
    listTableauConnections(true).catch(() => null),
  ]);

  // 处理数据源连接
  if (datasourceResult.status === 'fulfilled' && datasourceResult.value) {
    const { datasources } = datasourceResult.value;
    for (const ds of datasources) {
      if (ds.is_active) {
        results.push({
          id: ds.id,
          name: ds.name,
          type: mapDbType(ds.db_type),
        });
      }
    }
  }

  // 处理 Tableau 连接
  if (tableauResult.status === 'fulfilled' && tableauResult.value) {
    const { connections } = tableauResult.value;
    for (const conn of connections) {
      if (conn.is_active) {
        results.push({
          id: conn.id,
          name: conn.name,
          type: 'tableau' as ConnectionType,
        });
      }
    }
  }

  return results;
}
