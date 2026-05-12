import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { listConnections, type TableauConnection } from '../../api/tableau';

interface ScopeContextValue {
  connectionId: string | null;
  setConnectionId: (id: string | null) => void;
  scopeProject: string | null;
  setScopeProject: (id: string | null) => void;
  connections: TableauConnection[];
  connectionsLoading: boolean;
}

const ScopeContext = createContext<ScopeContextValue | null>(null);

interface ScopeProviderProps {
  children: ReactNode;
  initialConnectionId?: string | null;
  onConnectionIdChange?: (id: string | null) => void;
}

export function ScopeProvider({
  children,
  initialConnectionId = null,
  onConnectionIdChange,
}: ScopeProviderProps) {
  const [connectionId, setConnectionIdState] = useState<string | null>(null);
  const [scopeProject, setScopeProject] = useState<string | null>(null);
  const [connections, setConnections] = useState<TableauConnection[]>([]);
  const [connectionsLoading, setConnectionsLoading] = useState(true);

  const setConnectionId = useCallback((id: string | null) => {
    setConnectionIdState(id);
    onConnectionIdChange?.(id);
  }, [onConnectionIdChange]);

  useEffect(() => {
    setConnectionsLoading(true);
    listConnections(true)
      .then((res) => {
        const active = res.connections.filter((c) => c.is_active);
        setConnections(active);
      })
      .catch(() => {
        setConnections([]);
      })
      .finally(() => {
        setConnectionsLoading(false);
      });
  }, []);

  useEffect(() => {
    if (connectionsLoading) return;

    const requestedId = initialConnectionId ? String(initialConnectionId) : null;
    const requestedIsActive = requestedId
      ? connections.some((c) => String(c.id) === requestedId)
      : false;
    const nextConnectionId = requestedIsActive
      ? requestedId
      : (connections[0] ? String(connections[0].id) : null);

    setConnectionIdState((prev) => (
      prev === nextConnectionId ? prev : nextConnectionId
    ));

    if (requestedId !== nextConnectionId) {
      onConnectionIdChange?.(nextConnectionId);
    }
  }, [connections, connectionsLoading, initialConnectionId, onConnectionIdChange]);

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
