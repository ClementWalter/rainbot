import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useSession } from "./hooks/useSession";
import { LoginPage } from "./pages/LoginPage";
import { SearchesPage } from "./pages/SearchesPage";
import { HistoryPage } from "./pages/HistoryPage";
import { AdminUsersPage } from "./pages/AdminUsersPage";

// Top-level router: every non-login path is gated by RequireAuth, and the
// admin page additionally checks is_admin.  Loading state renders a blank
// shell so the layout chrome does not flash in before the session is known.

export function App() {
  const { loading } = useSession();

  if (loading) {
    return (
      <div className="center-stage">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/searches"
        element={
          <RequireAuth>
            <Layout>
              <SearchesPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/history"
        element={
          <RequireAuth>
            <Layout>
              <HistoryPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/admin/users"
        element={
          <RequireAuth adminOnly>
            <Layout>
              <AdminUsersPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route path="/" element={<DefaultRedirect />} />
      <Route path="*" element={<DefaultRedirect />} />
    </Routes>
  );
}

function RequireAuth({
  children,
  adminOnly,
}: {
  children: React.ReactElement;
  adminOnly?: boolean;
}) {
  const { user } = useSession();
  if (!user) return <Navigate to="/login" replace />;
  if (adminOnly && !user.is_admin) return <Navigate to="/searches" replace />;
  return children;
}

function DefaultRedirect() {
  const { user } = useSession();
  return <Navigate to={user ? "/searches" : "/login"} replace />;
}
