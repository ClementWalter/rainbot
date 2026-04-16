import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { Button } from "../components/Button";
import { Flash, type FlashMessage } from "../components/Flash";
import { GlassCard } from "../components/GlassCard";
import { Field, InputField } from "../components/Field";
import type { BurstWindow, SchedulerOverview } from "../api/types";

// Admin-only page for the background booking scheduler.  Mirrors the
// settings the Python service reads on every loop tick — toggling
// `enabled` or saving a new burst window takes effect within one tick of
// the next iteration without restarting the API.

export function AdminSchedulerPage() {
  const [overview, setOverview] = useState<SchedulerOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<FlashMessage | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.scheduler();
      setOverview(response);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load scheduler.";
      setFlash({ level: "error", message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleSave = async (patch: {
    enabled?: boolean;
    default_interval_seconds?: number;
    tick_noise_seconds?: number;
    burst_windows?: BurstWindow[];
  }) => {
    setBusy(true);
    try {
      const response = await api.updateScheduler(patch);
      setOverview((prev) =>
        prev ? { ...prev, settings: response.settings } : prev,
      );
      setFlash({ level: "success", message: "Scheduler settings saved." });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Save failed.";
      setFlash({ level: "error", message });
    } finally {
      setBusy(false);
    }
  };

  const handleRunNow = async () => {
    setBusy(true);
    setFlash(null);
    try {
      const response = await api.runScheduler();
      const succeeded =
        (response.summary as { bookings_succeeded?: number })
          .bookings_succeeded ?? 0;
      setFlash({
        level: succeeded > 0 ? "success" : "info",
        message: `Tick complete — ${succeeded} booking(s) succeeded.`,
      });
      await refresh();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Tick failed.";
      setFlash({ level: "error", message });
    } finally {
      setBusy(false);
    }
  };

  if (loading || !overview) {
    return (
      <GlassCard>
        <div className="skeleton" style={{ height: 96 }} />
      </GlassCard>
    );
  }

  return (
    <>
      <section>
        <h1>Scheduler</h1>
        <p className="muted">
          Background loop that polls active saved searches and books the moment
          a slot opens. Toggle off to halt all auto-booking; the loop keeps
          running so changes apply on the next tick.
        </p>
      </section>

      <Flash flash={flash} onClose={() => setFlash(null)} />

      <SchedulerSettingsCard
        overview={overview}
        busy={busy}
        onSave={handleSave}
        onRunNow={handleRunNow}
      />

      <RunsCard overview={overview} />
    </>
  );
}

function SchedulerSettingsCard({
  overview,
  busy,
  onSave,
  onRunNow,
}: {
  overview: SchedulerOverview;
  busy: boolean;
  onSave: (patch: {
    enabled?: boolean;
    default_interval_seconds?: number;
    tick_noise_seconds?: number;
    burst_windows?: BurstWindow[];
  }) => Promise<void>;
  onRunNow: () => Promise<void>;
}) {
  const settings = overview.settings;
  const [interval, setInterval_] = useState(settings.default_interval_seconds);
  const [tickNoise, setTickNoise] = useState(settings.tick_noise_seconds);
  const [burstWindows, setBurstWindows] = useState<BurstWindow[]>(
    settings.burst_windows,
  );

  // Whenever the server confirms a save, sync the local form so the inputs
  // reflect the canonical (clamped) values the API persisted.
  useEffect(() => {
    setInterval_(settings.default_interval_seconds);
    setTickNoise(settings.tick_noise_seconds);
    setBurstWindows(settings.burst_windows);
  }, [settings]);

  const handleAddWindow = () => {
    setBurstWindows((current) => [
      ...current,
      { time: "07:58", plus_minus_minutes: 5, interval_seconds: 5 },
    ]);
  };

  const handleRemoveWindow = (index: number) => {
    setBurstWindows((current) => current.filter((_, i) => i !== index));
  };

  const handleWindowChange = (
    index: number,
    patch: Partial<BurstWindow>,
  ) => {
    setBurstWindows((current) =>
      current.map((window, i) => (i === index ? { ...window, ...patch } : window)),
    );
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    await onSave({
      default_interval_seconds: interval,
      tick_noise_seconds: tickNoise,
      burst_windows: burstWindows,
    });
  };

  return (
    <GlassCard>
      <form className="stack" onSubmit={handleSubmit}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="stack" style={{ gap: "0.2rem" }}>
            <div className="row">
              <span className={`pill ${settings.enabled ? "positive" : "danger"}`}>
                {settings.enabled ? "Enabled" : "Disabled"}
              </span>
              <span style={{ fontSize: "0.9rem" }}>
                Polls every <strong>{settings.default_interval_seconds}s</strong>
                {settings.tick_noise_seconds > 0
                  ? ` ± ${settings.tick_noise_seconds}s jitter`
                  : ""}
              </span>
            </div>
            <span className="muted" style={{ fontSize: "0.78rem" }}>
              Tick interval bounded {settings.min_interval_seconds}s –{" "}
              {Math.round(settings.max_interval_seconds / 60)} min.
            </span>
          </div>
          <div className="row">
            <Button
              type="button"
              variant={settings.enabled ? "danger" : "primary"}
              onClick={() => onSave({ enabled: !settings.enabled })}
              disabled={busy}
            >
              {settings.enabled ? "Disable scheduler" : "Enable scheduler"}
            </Button>
            <Button type="button" onClick={onRunNow} disabled={busy}>
              {busy ? "Running…" : "Run now"}
            </Button>
          </div>
        </div>

        <div className="row" style={{ gap: "1rem" }}>
          <Field
            label="Default tick interval (seconds)"
            hint={`Bounded ${settings.min_interval_seconds}s – ${Math.round(
              settings.max_interval_seconds / 60,
            )} min.`}
          >
            <input
              type="number"
              min={settings.min_interval_seconds}
              max={settings.max_interval_seconds}
              value={interval}
              onChange={(e) => setInterval_(Number(e.target.value))}
            />
          </Field>
          <Field
            label="Tick jitter ± seconds"
            hint={`0 disables jitter. Bounded 0 – ${settings.max_tick_noise_seconds}s.`}
          >
            <input
              type="number"
              min={0}
              max={settings.max_tick_noise_seconds}
              value={tickNoise}
              onChange={(e) => setTickNoise(Number(e.target.value))}
            />
          </Field>
        </div>

        <Field
          label="Burst windows"
          hint="Within ±N minutes of the configured time, override the tick interval. Useful for the 08:00 booking opening."
        >
          <div className="stack" style={{ gap: "0.6rem" }}>
            {burstWindows.length === 0 ? (
              <p className="muted">No burst windows — only the default interval applies.</p>
            ) : (
              burstWindows.map((window, index) => (
                <BurstWindowRow
                  key={index}
                  window={window}
                  onChange={(patch) => handleWindowChange(index, patch)}
                  onRemove={() => handleRemoveWindow(index)}
                />
              ))
            )}
            <div>
              <Button type="button" onClick={handleAddWindow}>
                + Add burst window
              </Button>
            </div>
          </div>
        </Field>

        <div className="row" style={{ justifyContent: "flex-end" }}>
          <Button type="submit" variant="primary" disabled={busy}>
            Save settings
          </Button>
        </div>
      </form>
    </GlassCard>
  );
}

function BurstWindowRow({
  window,
  onChange,
  onRemove,
}: {
  window: BurstWindow;
  onChange: (patch: Partial<BurstWindow>) => void;
  onRemove: () => void;
}) {
  return (
    <div
      className="row"
      style={{ alignItems: "flex-end", gap: "0.6rem", flexWrap: "wrap" }}
    >
      <InputField
        label="Time (HH:MM)"
        value={window.time}
        onChange={(e) => onChange({ time: e.target.value })}
      />
      <InputField
        label="±minutes"
        type="number"
        min={0}
        max={120}
        value={window.plus_minus_minutes}
        onChange={(e) => onChange({ plus_minus_minutes: Number(e.target.value) })}
      />
      <InputField
        label="Tick (s)"
        type="number"
        min={5}
        max={3600}
        value={window.interval_seconds}
        onChange={(e) => onChange({ interval_seconds: Number(e.target.value) })}
      />
      <Button type="button" variant="danger" onClick={onRemove}>
        Remove
      </Button>
    </div>
  );
}

/** Format an ISO timestamp + optional end into "Wed 09:41 (6s)". */
function formatTickTime(startedAt: string, finishedAt?: string | null): string {
  const start = new Date(startedAt);
  const day = start.toLocaleDateString("en-GB", { weekday: "short" });
  const time = start.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (!finishedAt) return `${day} ${time} (running)`;
  const end = new Date(finishedAt);
  const durationMs = end.getTime() - start.getTime();
  const durationSec = Math.round(durationMs / 1000);
  const durationLabel =
    durationSec < 60
      ? `${durationSec}s`
      : `${Math.floor(durationSec / 60)}m${String(durationSec % 60).padStart(2, "0")}s`;
  return `${day} ${time} (${durationLabel})`;
}

function RunsCard({ overview }: { overview: SchedulerOverview }) {
  const runs = overview.runs;
  return (
    <GlassCard>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Recent ticks</h2>
        <span className="pill">{runs.length} entries</span>
      </div>
      {runs.length === 0 ? (
        <p className="empty-state">No ticks recorded yet.</p>
      ) : (
        <div className="stack" style={{ gap: "0.5rem", marginTop: "0.8rem" }}>
          {runs.map((run) => (
            <details
              key={run.id}
              style={{
                background: "rgba(255,255,255,0.04)",
                borderRadius: "var(--radius-md)",
                padding: "0.6rem 0.8rem",
                border: "1px solid var(--glass-border)",
              }}
            >
              <summary style={{ cursor: "pointer", listStyle: "none" }}>
                <span className="muted" style={{ fontSize: "0.85rem" }}>
                  #{run.id} · {formatTickTime(run.started_at, run.finished_at)}
                </span>{" "}
                <RunHeadline summary={run.summary} />
              </summary>
              <pre
                style={{
                  marginTop: "0.6rem",
                  padding: "0.6rem 0.8rem",
                  borderRadius: "var(--radius-sm)",
                  background: "rgba(0,0,0,0.25)",
                  color: "var(--ink)",
                  fontSize: "0.78rem",
                  overflow: "auto",
                }}
              >
                {JSON.stringify(run.summary, null, 2)}
              </pre>
            </details>
          ))}
        </div>
      )}
    </GlassCard>
  );
}

function RunHeadline({ summary }: { summary: Record<string, unknown> }) {
  const succeeded = Number(summary["bookings_succeeded"] ?? 0);
  const evaluated = Number(summary["users_evaluated"] ?? 0);
  const skipped = Number(summary["users_skipped_pending"] ?? 0);
  const tone = succeeded > 0 ? "positive" : "";
  return (
    <span className={`pill ${tone}`}>
      {succeeded} booked · {evaluated} users · {skipped} skipped
    </span>
  );
}
