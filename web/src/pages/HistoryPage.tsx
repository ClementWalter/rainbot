import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { Button } from "../components/Button";
import { Flash, type FlashMessage } from "../components/Flash";
import { GlassCard } from "../components/GlassCard";
import type { BookingRecord, PendingReservation } from "../api/types";

// History paints instantly from the local SQLite store; the live pending
// reservation is a separate fetch so the slow Playwright round-trip does not
// block first paint.

export function HistoryPage() {
  const [records, setRecords] = useState<BookingRecord[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(true);
  const [pending, setPending] = useState<PendingReservation | null>(null);
  const [pendingLoading, setPendingLoading] = useState(true);
  const [pendingFlash, setPendingFlash] = useState<FlashMessage | null>(null);
  const [recordsFlash, setRecordsFlash] = useState<FlashMessage | null>(null);
  const [canceling, setCanceling] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const response = await api.history();
        setRecords(response.records);
      } catch (error) {
        const message =
          error instanceof ApiError ? error.message : "Could not load history.";
        setRecordsFlash({ level: "error", message });
      } finally {
        setRecordsLoading(false);
      }
    })();
  }, []);

  const refreshPending = useCallback(async () => {
    setPendingLoading(true);
    setPendingFlash(null);
    try {
      const response = await api.pendingReservation();
      setPending(response.pending);
      if (response.error) {
        setPendingFlash({ level: "error", message: response.error });
      }
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Could not load live reservation status.";
      setPendingFlash({ level: "error", message });
    } finally {
      setPendingLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshPending();
  }, [refreshPending]);

  const handleCancel = async () => {
    if (!confirm("Cancel the active reservation on tennis.paris.fr?")) return;
    setCanceling(true);
    setPendingFlash(null);
    try {
      const response = await api.cancelPendingReservation();
      setPendingFlash({
        level: response.canceled ? "success" : "info",
        message: response.canceled
          ? "Reservation canceled."
          : "No active reservation to cancel.",
      });
      await refreshPending();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Cancellation failed.";
      setPendingFlash({ level: "error", message });
    } finally {
      setCanceling(false);
    }
  };

  return (
    <>
      <section>
        <h1>History</h1>
        <p className="muted">
          Bookings this app has made under your account, plus the live
          reservation status pulled from tennis.paris.fr.
        </p>
      </section>

      <GlassCard>
        <h2>Pending reservation (live)</h2>
        {pendingLoading ? (
          <p className="muted">Loading live reservation status…</p>
        ) : pendingFlash ? (
          <Flash flash={pendingFlash} />
        ) : pending?.has_active_reservation ? (
          <PendingReservation
            pending={pending}
            canceling={canceling}
            onCancel={handleCancel}
          />
        ) : pending ? (
          <>
            <p className="muted">No active reservation currently detected.</p>
            <ProfileBalances rawText={pending.raw_text} />
          </>
        ) : (
          <p className="muted">No reservation data available.</p>
        )}
      </GlassCard>

      <section>
        <h2>Booking history</h2>
        <Flash flash={recordsFlash} onClose={() => setRecordsFlash(null)} />
      </section>

      <section className="card-list">
        {recordsLoading ? (
          <GlassCard>
            <div className="skeleton" style={{ height: 72 }} />
          </GlassCard>
        ) : records.length === 0 ? (
          <GlassCard>
            <p className="empty-state">No bookings recorded yet.</p>
          </GlassCard>
        ) : (
          records.map((record) => (
            <GlassCard key={record.id}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h3 style={{ margin: 0 }}>{record.venue_name}</h3>
                <span className="pill positive">{record.booked_at}</span>
              </div>
              <p style={{ marginTop: "0.4rem" }}>
                {record.date_deb} → {record.date_fin}
              </p>
              <p className="muted" style={{ fontSize: "0.85rem" }}>
                {record.court_name || `court=${record.court_id}`} · price=
                {record.price_eur} ({record.price_label})
              </p>
            </GlassCard>
          ))
        )}
      </section>
    </>
  );
}

// Pull "Crédit d'absence" / "Nombre d'heures" lines out of the trimmed
// profile text dump so the balances render as their own pills.  Anything
// that doesn't match either pattern falls into the "remainder" tail and is
// shown as muted text — no parsing wizardry, just a couple of substrings.
function ProfileBalances({ rawText }: { rawText: string }) {
  const trimmed = rawText.trim();
  if (!trimmed) return null;
  const balanceMatchers: { pill: string; pattern: RegExp }[] = [
    { pill: "Absence credit", pattern: /Crédit d'absence\s*:?\s*([\d/ ]+\d)/i },
    { pill: "Hours left", pattern: /Nombre d'heures restantes\s*:?\s*([\d/ ]+\d)/i },
  ];
  const pills: { label: string; value: string }[] = [];
  for (const matcher of balanceMatchers) {
    const match = trimmed.match(matcher.pattern);
    if (match) pills.push({ label: matcher.pill, value: match[1].trim() });
  }
  if (pills.length === 0) {
    return (
      <p className="muted" style={{ marginTop: "0.6rem", fontSize: "0.85rem" }}>
        {trimmed.slice(0, 240)}
        {trimmed.length > 240 ? "…" : ""}
      </p>
    );
  }
  return (
    <div
      className="row"
      style={{ marginTop: "0.6rem", gap: "0.4rem", flexWrap: "wrap" }}
    >
      {pills.map((pill) => (
        <span key={pill.label} className="pill">
          {pill.label}: {pill.value}
        </span>
      ))}
    </div>
  );
}

// Renders the live reservation in the same shape as a booked-history card
// using the parser's structured `details` block.  Falls back to the trimmed
// raw_text when details are unavailable (e.g. older page format).
function PendingReservation({
  pending,
  canceling,
  onCancel,
}: {
  pending: PendingReservation;
  canceling: boolean;
  onCancel: () => void;
}) {
  const details = pending.details;
  if (!details) {
    // No structured fields — show the trimmed text dump as a last resort
    // so the user still sees *something* useful.
    return (
      <>
        <span className="pill positive">Reservation active</span>
        <p className="muted" style={{ marginTop: "0.6rem", fontSize: "0.85rem" }}>
          {pending.raw_text.slice(0, 320)}
          {pending.raw_text.length > 320 ? "…" : ""}
        </p>
        <div className="row" style={{ marginTop: "0.8rem" }}>
          <Button variant="danger" onClick={onCancel} disabled={canceling}>
            {canceling ? "Cancelling…" : "Cancel reservation"}
          </Button>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>{details.venue || "Reservation active"}</h3>
        <span className="pill positive">Active</span>
      </div>
      {details.address ? (
        <p className="muted" style={{ fontSize: "0.85rem", margin: "0.2rem 0 0.4rem" }}>
          {details.address}
        </p>
      ) : null}
      {details.date_label || details.hours_label ? (
        <p style={{ margin: "0.4rem 0" }}>
          {details.date_label}
          {details.date_label && details.hours_label ? " · " : ""}
          {details.hours_label}
        </p>
      ) : null}
      {details.court_label ? (
        <p className="muted" style={{ fontSize: "0.9rem" }}>
          {details.court_label}
        </p>
      ) : null}
      <div
        className="row"
        style={{ marginTop: "0.6rem", flexWrap: "wrap", gap: "0.4rem" }}
      >
        {details.entry_label ? (
          <span className="pill">{details.entry_label}</span>
        ) : null}
        {details.balance_label ? (
          <span className="pill">{details.balance_label}</span>
        ) : null}
      </div>
      {details.cancel_deadline ? (
        <p className="muted" style={{ fontSize: "0.78rem", marginTop: "0.6rem" }}>
          {details.cancel_deadline}
        </p>
      ) : null}
      <div className="row" style={{ marginTop: "0.8rem" }}>
        <Button variant="danger" onClick={onCancel} disabled={canceling}>
          {canceling ? "Cancelling…" : "Cancel reservation"}
        </Button>
      </div>
    </>
  );
}
