import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

interface ProtectedRouteProps {
  children: React.ReactNode;
  adminOnly?: boolean;
  requiredPermission?: string;
}

export default function ProtectedRoute({ children, adminOnly = false, requiredPermission }: ProtectedRouteProps) {
  const { user, loading, hasPermission } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-slate-500">加载中...</div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (adminOnly && user.role !== 'admin') {
    return <Navigate to="/403" state={{ from: location }} replace />;
  }

  // Check specific permission (non-admin users)
  if (requiredPermission && !hasPermission(requiredPermission)) {
    return <Navigate to="/403" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
