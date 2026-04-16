import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { Button } from "../components/Button";
import { Flash, type FlashMessage } from "../components/Flash";
import { GlassCard } from "../components/GlassCard";
import { InputField } from "../components/Field";
import type { User } from "../api/types";

export function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [flash, setFlash] = useState<FlashMessage | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.listUsers();
      setUsers(response.users);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load users.";
      setFlash({ level: "error", message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async (body: CreateUserInput) => {
    try {
      await api.createUser(body);
      setFlash({ level: "success", message: "User added to allow-list." });
      await refresh();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not add user.";
      setFlash({ level: "error", message });
    }
  };

  const handleUpdate = async (
    user: User,
    patch: {
      display_name?: string;
      paris_username?: string;
      paris_password?: string;
      is_admin?: boolean;
      is_enabled?: boolean;
    },
  ) => {
    try {
      const updated = await api.updateUser(user.id, patch);
      setUsers((current) =>
        current.map((u) => (u.id === user.id ? updated.user : u)),
      );
      setFlash({ level: "success", message: `${updated.user.display_name} updated.` });
      return true;
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Update failed.";
      setFlash({ level: "error", message });
      return false;
    }
  };

  const handleDelete = async (user: User) => {
    try {
      await api.deleteUser(user.id);
      setFlash({
        level: "success",
        message: `${user.display_name} deleted.`,
      });
      setUsers((current) => current.filter((u) => u.id !== user.id));
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Delete failed.";
      setFlash({ level: "error", message });
    }
  };

  const [checkingLogin, setCheckingLogin] = useState<number | null>(null);

  const handleCheckLogin = async (user: User) => {
    setCheckingLogin(user.id);
    setFlash(null);
    try {
      const result = await api.checkUserLogin(user.id);
      setFlash({
        level: result.ok ? "success" : "error",
        message: `${user.display_name}: ${result.detail}`,
      });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Check failed.";
      setFlash({ level: "error", message: `${user.display_name}: ${message}` });
    } finally {
      setCheckingLogin(null);
    }
  };

  return (
    <>
      <section>
        <h1>Users</h1>
        <p className="muted">
          Allow-listed accounts that can sign into this booker.
        </p>
      </section>

      <Flash flash={flash} onClose={() => setFlash(null)} />

      <GlassCard>
        <CreateUserForm onSubmit={handleCreate} />
      </GlassCard>

      <section className="card-list">
        {loading ? (
          <GlassCard>
            <div className="skeleton" style={{ height: 72 }} />
          </GlassCard>
        ) : (
          users.map((user) => (
            <UserCard
              key={user.id}
              user={user}
              checkingLogin={checkingLogin === user.id}
              onCheckLogin={() => handleCheckLogin(user)}
              onUpdate={(patch) => handleUpdate(user, patch)}
              onDelete={() => handleDelete(user)}
            />
          ))
        )}
      </section>
    </>
  );
}

// ----------------------------------------------------------------- UserCard

function UserCard({
  user,
  checkingLogin,
  onCheckLogin,
  onUpdate,
  onDelete,
}: {
  user: User;
  checkingLogin: boolean;
  onCheckLogin: () => void;
  onUpdate: (patch: {
    display_name?: string;
    paris_username?: string;
    paris_password?: string;
    is_admin?: boolean;
    is_enabled?: boolean;
  }) => Promise<boolean>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [saving, setSaving] = useState(false);

  // Edit form state — pre-filled from current user.
  const [displayName, setDisplayName] = useState(user.display_name);
  const [parisUsername, setParisUsername] = useState(user.paris_username);
  const [parisPassword, setParisPassword] = useState("");

  // Reset form when user prop changes (e.g. after save).
  useEffect(() => {
    setDisplayName(user.display_name);
    setParisUsername(user.paris_username);
    setParisPassword("");
  }, [user]);

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    // Only send fields that actually changed.
    const patch: Record<string, string> = {};
    if (displayName.trim() !== user.display_name) {
      patch.display_name = displayName.trim();
    }
    if (parisUsername.trim() !== user.paris_username) {
      patch.paris_username = parisUsername.trim();
    }
    if (parisPassword) {
      patch.paris_password = parisPassword;
    }
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      setSaving(false);
      return;
    }
    const ok = await onUpdate(patch);
    setSaving(false);
    if (ok) setEditing(false);
  };

  return (
    <GlassCard>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="row">
            <h2 style={{ margin: 0 }}>{user.display_name}</h2>
            {user.is_admin ? (
              <span className="pill positive">Admin</span>
            ) : (
              <span className="pill">User</span>
            )}
            <span className={`pill ${user.is_enabled ? "" : "danger"}`}>
              {user.is_enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          <p className="muted" style={{ margin: "0.3rem 0 0" }}>
            {user.paris_username}
          </p>
        </div>
        <div className="row">
          <Button onClick={onCheckLogin} disabled={checkingLogin}>
            {checkingLogin ? "Checking\u2026" : "Check login"}
          </Button>
          <Button onClick={() => setEditing(!editing)}>
            {editing ? "Cancel" : "Edit"}
          </Button>
          <Button
            onClick={() => onUpdate({ is_admin: !user.is_admin })}
          >
            {user.is_admin ? "Revoke admin" : "Make admin"}
          </Button>
          <Button
            onClick={() => onUpdate({ is_enabled: !user.is_enabled })}
          >
            {user.is_enabled ? "Disable" : "Enable"}
          </Button>
          {confirmDelete ? (
            <>
              <Button variant="danger" onClick={onDelete}>
                Confirm delete
              </Button>
              <Button onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <Button variant="danger" onClick={() => setConfirmDelete(true)}>
              Delete
            </Button>
          )}
        </div>
      </div>

      {editing && (
        <form className="stack" style={{ marginTop: "1rem" }} onSubmit={handleSave}>
          <div className="row" style={{ gap: "1rem" }}>
            <InputField
              label="Display name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
            />
            <InputField
              label="Paris username"
              value={parisUsername}
              onChange={(e) => setParisUsername(e.target.value)}
              required
            />
            <InputField
              label="New Paris password"
              type="password"
              value={parisPassword}
              onChange={(e) => setParisPassword(e.target.value)}
              placeholder="leave empty to keep current"
            />
          </div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <Button type="submit" variant="primary" disabled={saving}>
              {saving ? "Saving\u2026" : "Save changes"}
            </Button>
          </div>
        </form>
      )}
    </GlassCard>
  );
}

// ----------------------------------------------------------------- CreateUserForm

type CreateUserInput = {
  display_name: string;
  paris_username: string;
  paris_password: string;
  is_admin: boolean;
};

function CreateUserForm({
  onSubmit,
}: {
  onSubmit: (body: CreateUserInput) => void | Promise<void>;
}) {
  const [displayName, setDisplayName] = useState("");
  const [parisUsername, setParisUsername] = useState("");
  const [parisPassword, setParisPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    await onSubmit({
      display_name: displayName,
      paris_username: parisUsername,
      paris_password: parisPassword,
      is_admin: isAdmin,
    });
    setDisplayName("");
    setParisUsername("");
    setParisPassword("");
    setIsAdmin(false);
  };

  return (
    <form className="stack" onSubmit={handleSubmit}>
      <span className="pill">Add user</span>
      <div className="row" style={{ gap: "1rem" }}>
        <InputField
          label="Display name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          required
        />
        <InputField
          label="Paris username"
          value={parisUsername}
          onChange={(e) => setParisUsername(e.target.value)}
          required
        />
        <InputField
          label="Paris password"
          type="password"
          value={parisPassword}
          onChange={(e) => setParisPassword(e.target.value)}
          required
        />
      </div>
      <label
        className={`chip ${isAdmin ? "selected" : ""}`.trim()}
        style={{ alignSelf: "flex-start" }}
      >
        <input
          type="checkbox"
          checked={isAdmin}
          onChange={(e) => setIsAdmin(e.target.checked)}
        />
        <span>Grant admin role</span>
      </label>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <Button type="submit" variant="primary">
          Add user
        </Button>
      </div>
    </form>
  );
}
