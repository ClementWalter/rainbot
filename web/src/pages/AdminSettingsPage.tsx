import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { Button } from "../components/Button";
import { Flash, type FlashMessage } from "../components/Flash";
import { GlassCard } from "../components/GlassCard";
import type { AppSettings } from "../api/types";

// Admin page for runtime-configurable settings (captcha key, etc.)
// stored in the DB so they survive container restarts without env vars.

export function AdminSettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<FlashMessage | null>(null);
  const [captchaKey, setCaptchaKey] = useState("");
  const [showKey, setShowKey] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.settings();
      setSettings(response.settings);
      setCaptchaKey(response.settings.captcha_api_key);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load settings.";
      setFlash({ level: "error", message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const response = await api.updateSettings({
        captcha_api_key: captchaKey,
      });
      setSettings(response.settings);
      setCaptchaKey(response.settings.captcha_api_key);
      setFlash({ level: "success", message: "Settings saved." });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Save failed.";
      setFlash({ level: "error", message });
    } finally {
      setBusy(false);
    }
  };

  if (loading || !settings) {
    return (
      <GlassCard>
        <div className="skeleton" style={{ height: 96 }} />
      </GlassCard>
    );
  }

  return (
    <>
      <section>
        <h1>Settings</h1>
        <p className="muted">
          Runtime configuration stored in the database. Changes take effect
          immediately without restarting the server.
        </p>
      </section>

      <Flash flash={flash} onClose={() => setFlash(null)} />

      <GlassCard>
        <form className="stack" onSubmit={handleSubmit}>
          <div className="stack" style={{ gap: "0.3rem" }}>
            <label htmlFor="captcha-key" style={{ fontWeight: 600 }}>
              Captcha API key (2captcha)
            </label>
            <p className="muted" style={{ margin: 0, fontSize: "0.82rem" }}>
              Required for automated booking. Without it the scheduler and
              manual booking will fail.
            </p>
            <div className="row" style={{ gap: "0.4rem" }}>
              <input
                id="captcha-key"
                type={showKey ? "text" : "password"}
                value={captchaKey}
                onChange={(e) => setCaptchaKey(e.target.value)}
                placeholder="2captcha API key"
                autoComplete="off"
                style={{ flex: 1 }}
              />
              <Button
                type="button"
                variant="ghost"
                onClick={() => setShowKey((v) => !v)}
              >
                {showKey ? "Hide" : "Show"}
              </Button>
            </div>
          </div>

          <div className="row" style={{ justifyContent: "flex-end" }}>
            <span
              className={`pill ${settings.captcha_api_key ? "positive" : "danger"}`}
            >
              {settings.captcha_api_key ? "Key configured" : "Key missing"}
            </span>
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Saving..." : "Save settings"}
            </Button>
          </div>
        </form>
      </GlassCard>
    </>
  );
}
