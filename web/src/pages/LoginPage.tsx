import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { Button } from "../components/Button";
import { Flash, type FlashMessage } from "../components/Flash";
import { GlassCard } from "../components/GlassCard";
import { InputField } from "../components/Field";
import { useSession } from "../hooks/useSession";

// The login page doubles as the first-run bootstrap: when the store is empty,
// it reveals a display-name field so the admin can be created in one submit.

export function LoginPage() {
  const { needsBootstrap, refresh } = useSession();
  const navigate = useNavigate();
  const [parisUsername, setParisUsername] = useState("");
  const [parisPassword, setParisPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [flash, setFlash] = useState<FlashMessage | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFlash(null);
    setBusy(true);
    try {
      if (needsBootstrap) {
        await api.bootstrapAdmin({
          display_name: displayName,
          paris_username: parisUsername,
          paris_password: parisPassword,
        });
      } else {
        await api.login(parisUsername, parisPassword);
      }
      await refresh();
      navigate("/searches", { replace: true });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Something went wrong.";
      setFlash({ level: "error", message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="center-stage">
      <GlassCard style={{ width: "min(420px, 100%)" }}>
        <div className="stack">
          <div>
            <span className="pill">
              {needsBootstrap ? "First-run setup" : "Sign in"}
            </span>
            <h1 style={{ marginTop: "0.8rem" }}>
              {needsBootstrap ? "Welcome — set up your admin" : "Rainbot"}
            </h1>
            <p className="muted">
              {needsBootstrap
                ? "Create the first admin with the same username and password you use on tennis.paris.fr."
                : "Use your tennis.paris.fr credentials. Bookings will run under that account."}
            </p>
          </div>

          <Flash flash={flash} onClose={() => setFlash(null)} />

          <form className="stack" onSubmit={onSubmit}>
            {needsBootstrap ? (
              <InputField
                label="Display name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="name"
                required
              />
            ) : null}
            <InputField
              label="Tennis username"
              value={parisUsername}
              onChange={(e) => setParisUsername(e.target.value)}
              autoComplete="username"
              required
            />
            <InputField
              label="Tennis password"
              type="password"
              value={parisPassword}
              onChange={(e) => setParisPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
            <Button type="submit" variant="primary" disabled={busy}>
              {busy
                ? "Working…"
                : needsBootstrap
                  ? "Create admin & sign in"
                  : "Sign in"}
            </Button>
          </form>
        </div>
      </GlassCard>
    </div>
  );
}
