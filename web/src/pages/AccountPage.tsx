import { useState } from "react";
import { api, ApiError } from "../api/client";
import { useSession } from "../hooks/useSession";
import { Button } from "../components/Button";
import { Flash, type FlashMessage } from "../components/Flash";
import { GlassCard } from "../components/GlassCard";
import { InputField } from "../components/Field";

/** Self-service profile page — any authenticated user can edit their own info.
 *  Credential changes are validated server-side via a live login check. */
export function AccountPage() {
  const { user, setUser } = useSession();

  const [flash, setFlash] = useState<FlashMessage | null>(null);
  const [saving, setSaving] = useState(false);

  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [parisUsername, setParisUsername] = useState(user?.paris_username ?? "");
  const [parisPassword, setParisPassword] = useState("");

  if (!user) return null;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFlash(null);
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
      setFlash({ level: "success", message: "Nothing to change." });
      setSaving(false);
      return;
    }

    try {
      const result = await api.updateMe(patch);
      setUser(result.user);
      setParisPassword("");
      setFlash({ level: "success", message: "Profile updated." });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Update failed.";
      setFlash({ level: "error", message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <section>
        <h1>My Account</h1>
        <p className="muted">
          Edit your profile. Changing your username or password will trigger a
          live login check — the update is rejected if the new credentials are
          invalid.
        </p>
      </section>

      <Flash flash={flash} onClose={() => setFlash(null)} />

      <GlassCard>
        <form className="stack" onSubmit={handleSubmit}>
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
      </GlassCard>
    </>
  );
}
