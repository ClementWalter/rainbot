import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useSession } from "../hooks/useSession";
import { Button } from "./Button";

// Shell rendered around every authenticated page: glassy sticky topbar with
// the Paris brand mark, nav links, and a logout control.
export function Layout({ children }: { children: ReactNode }) {
  const { user, refresh } = useSession();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await api.logout();
    await refresh();
    navigate("/login", { replace: true });
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden />
          <div className="brand-title">
            <span className="eyebrow">Sometime it rains</span>
            <span className="name">Rainbot</span>
          </div>
        </div>
        {user ? (
          <nav className="topbar-nav">
            <NavLink
              to="/searches"
              className={({ isActive }) =>
                `nav-link ${isActive ? "active" : ""}`.trim()
              }
            >
              Searches
            </NavLink>
            <NavLink
              to="/history"
              className={({ isActive }) =>
                `nav-link ${isActive ? "active" : ""}`.trim()
              }
            >
              History
            </NavLink>
            <NavLink
              to="/account"
              className={({ isActive }) =>
                `nav-link ${isActive ? "active" : ""}`.trim()
              }
            >
              Account
            </NavLink>
            {user.is_admin ? (
              <>
                <NavLink
                  to="/admin/users"
                  className={({ isActive }) =>
                    `nav-link ${isActive ? "active" : ""}`.trim()
                  }
                >
                  Users
                </NavLink>
                <NavLink
                  to="/admin/scheduler"
                  className={({ isActive }) =>
                    `nav-link ${isActive ? "active" : ""}`.trim()
                  }
                >
                  Scheduler
                </NavLink>
                <NavLink
                  to="/admin/settings"
                  className={({ isActive }) =>
                    `nav-link ${isActive ? "active" : ""}`.trim()
                  }
                >
                  Settings
                </NavLink>
              </>
            ) : null}
            <span className="pill">{user.display_name}</span>
            <Button variant="ghost" onClick={handleLogout}>
              Logout
            </Button>
          </nav>
        ) : null}
      </header>
      <main className="page">{children}</main>
    </div>
  );
}
