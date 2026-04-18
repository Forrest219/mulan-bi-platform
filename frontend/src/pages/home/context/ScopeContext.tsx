import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { listConnections, type TableauConnection } from '../../../api/tableau';

interface ScopeContextValue {
  connectionId: string | null;
  setConnectionId: (id: string | null) => void;
  scopeProject: string | null;
  setScopeProject: (id: string | null) => void;
  connections: TableauConnection[];
  connectionsLoading: boolean;
}

const ScopeContext = createContext<ScopeContextValue | null>(null);

export function ScopeProvider({ children }: { children: ReactNode }) {
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [scopeProject, setScopeProject] = useState<string | null>(null);
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [connectionsLoading, setConnectionsLoading] = useState(true);

  useEffect(() => {
    setConnectionsLoading(true);
    listConnections(true)
      .then((res) => {
        const active = res.connections.filter((c) => c.is_active);
        setConnections(active);
        // 默认不自动选中，保持 null（表示全部连接）
      })
      .catch(() => {
        setConnections([]);
      })
      .finally(() => {
        setConnectionsLoading(false);
      });
  }, []);

  return (
    <ScopeContext.Provider
      value={{
        connectionId,
        setConnectionId,
        scopeProject,
        setScopeProject,
        connections,
        connectionsLoading,
      }}
    >
      {children}
    </ScopeContext.Provider>
  );
}

export function useScope(): ScopeContextValue {
  const ctx = useContext(ScopeContext);
  if (!ctx) {
    throw new Error('useScope must be used within a ScopeProvider');
  }
  return ctx;
}

export { ScopeContext };
