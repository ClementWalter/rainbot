import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { Button } from "../components/Button";
import { Flash, type FlashMessage } from "../components/Flash";
import { GlassCard } from "../components/GlassCard";
import { InputField, Field } from "../components/Field";
import type {
  AvailabilityResponse,
  Catalog,
  SavedSearch,
} from "../api/types";

// Weekdays kept local so the form can render without waiting for the catalog.
const WEEKDAYS: { value: string; label: string }[] = [
  { value: "monday", label: "Monday" },
  { value: "tuesday", label: "Tuesday" },
  { value: "wednesday", label: "Wednesday" },
  { value: "thursday", label: "Thursday" },
  { value: "friday", label: "Friday" },
  { value: "saturday", label: "Saturday" },
  { value: "sunday", label: "Sunday" },
];

export function SearchesPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [loading, setLoading] = useState(true);
  const [flash, setFlash] = useState<FlashMessage | null>(null);
  const [busySearchId, setBusySearchId] = useState<number | null>(null);
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [availability, setAvailability] = useState<
    Record<number, AvailabilityResponse>
  >({});

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [catalogResponse, searchesResponse] = await Promise.all([
        api.catalog().catch(() => null),
        api.listSearches(),
      ]);
      setCatalog(catalogResponse);
      setSearches(searchesResponse.searches);
    } catch (error) {
      if (error instanceof ApiError) {
        setFlash({ level: "error", message: error.message });
      } else {
        throw error;
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const handleCreate = async (body: SavedSearchInput) => {
    try {
      await api.createSearch(body);
      setFlash({ level: "success", message: "Saved search created." });
      await loadAll();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not save.";
      setFlash({ level: "error", message });
    }
  };

  const handleToggle = async (search: SavedSearch) => {
    try {
      const updated = await api.updateSearch(search.id, {
        is_active: !search.is_active,
      });
      setSearches((current) =>
        current.map((s) => (s.id === search.id ? updated.search : s)),
      );
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Update failed.";
      setFlash({ level: "error", message });
    }
  };

  const handleDelete = async (search: SavedSearch) => {
    if (!confirm(`Delete "${search.label}"?`)) return;
    try {
      await api.deleteSearch(search.id);
      setSearches((current) => current.filter((s) => s.id !== search.id));
      setFlash({ level: "info", message: "Saved search deleted." });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Delete failed.";
      setFlash({ level: "error", message });
    }
  };

  const handleBook = async (search: SavedSearch) => {
    setBusySearchId(search.id);
    setFlash(null);
    try {
      await api.bookSearch(search.id);
      setFlash({
        level: "success",
        message: "Booking created — check /history for details.",
      });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Booking failed.";
      setFlash({ level: "error", message });
    } finally {
      setBusySearchId(null);
    }
  };

  const handleCheckAvailability = async (search: SavedSearch) => {
    setCheckingId(search.id);
    setFlash(null);
    try {
      const response = await api.checkAvailability(search.id);
      setAvailability((current) => ({ ...current, [search.id]: response }));
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Check failed.";
      setFlash({ level: "error", message });
    } finally {
      setCheckingId(null);
    }
  };

  const handleDuplicate = async (search: SavedSearch) => {
    try {
      await api.duplicateSearch(search.id);
      setFlash({ level: "success", message: "Saved search duplicated." });
      await loadAll();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Duplicate failed.";
      setFlash({ level: "error", message });
    }
  };

  const clearAvailability = (id: number) => {
    setAvailability((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
  };

  const handleEditSubmit = async (id: number, body: SavedSearchInput) => {
    try {
      const updated = await api.updateSearch(id, body);
      setSearches((current) =>
        current.map((s) => (s.id === id ? updated.search : s)),
      );
      setEditingId(null);
      setFlash({ level: "success", message: "Saved search updated." });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Update failed.";
      setFlash({ level: "error", message });
    }
  };

  return (
    <>
      <section>
        <h1>Saved searches</h1>
        <p className="muted">
          Alarms that book Paris Tennis courts on your behalf the moment a
          slot matching your criteria opens up.
        </p>
      </section>

      <Flash flash={flash} onClose={() => setFlash(null)} />

      <GlassCard>
        <SearchForm
          mode="create"
          catalog={catalog}
          disabled={loading}
          submitLabel="Save search"
          onSubmit={handleCreate}
        />
      </GlassCard>

      <section className="card-list">
        {loading ? (
          <GlassCard>
            <div className="skeleton" style={{ height: 72 }} />
          </GlassCard>
        ) : searches.length === 0 ? (
          <GlassCard>
            <p className="empty-state">
              No saved searches yet. Use the form above to create one.
            </p>
          </GlassCard>
        ) : (
          searches.map((search) => (
            <SavedSearchCard
              key={search.id}
              search={search}
              catalog={catalog}
              editing={editingId === search.id}
              booking={busySearchId === search.id}
              checking={checkingId === search.id}
              availability={availability[search.id]}
              onToggle={() => handleToggle(search)}
              onDelete={() => handleDelete(search)}
              onBook={() => handleBook(search)}
              onCheckAvailability={() => handleCheckAvailability(search)}
              onDuplicate={() => handleDuplicate(search)}
              onClearAvailability={() => clearAvailability(search.id)}
              onEdit={() => setEditingId(search.id)}
              onCancelEdit={() => setEditingId(null)}
              onEditSubmit={(body) => handleEditSubmit(search.id, body)}
            />
          ))
        )}
      </section>
    </>
  );
}

type SavedSearchInput = {
  label: string;
  venue_names: string[];
  weekday: string;
  hour_start: number;
  hour_end: number;
  in_out_codes: string[];
};

// Shared form used both for "new saved search" and "edit existing search".
// Initial values come from `initial` so it remounts cleanly per-search; the
// parent decides what action labels to show via `submitLabel`/`onCancel`.
function SearchForm({
  mode,
  catalog,
  disabled,
  submitLabel,
  onSubmit,
  onCancel,
  initial,
}: {
  mode: "create" | "edit";
  catalog: Catalog | null;
  disabled?: boolean;
  submitLabel: string;
  onSubmit: (body: SavedSearchInput) => void | Promise<void>;
  onCancel?: () => void;
  initial?: SavedSearchInput;
}) {
  const minHour = catalog?.min_hour ?? 8;
  const maxHour = catalog?.max_hour ?? 22;
  const [label, setLabel] = useState(initial?.label ?? "Morning alarm");
  const [venueNames, setVenueNames] = useState<string[]>(
    initial?.venue_names ?? [],
  );
  const [weekday, setWeekday] = useState(initial?.weekday ?? "sunday");
  const [hourStart, setHourStart] = useState(initial?.hour_start ?? minHour);
  const [hourEnd, setHourEnd] = useState(
    initial?.hour_end ?? Math.min(minHour + 2, maxHour),
  );
  const [inOutCodes, setInOutCodes] = useState<string[]>(
    initial?.in_out_codes ?? [],
  );

  // For new-search mode, default in_out to "all" once the catalog loads so an
  // empty user selection doesn't accidentally over-filter the search.  Edit
  // mode keeps whatever the user originally saved.
  useEffect(() => {
    if (mode !== "create") return;
    if (catalog && inOutCodes.length === 0) {
      setInOutCodes(catalog.in_out_options.map((o) => o.code));
    }
  }, [catalog, inOutCodes.length, mode]);

  const venueOptions = useMemo(() => catalog?.venues ?? [], [catalog]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    await onSubmit({
      label,
      venue_names: venueNames,
      weekday,
      hour_start: hourStart,
      hour_end: hourEnd,
      in_out_codes: inOutCodes,
    });
  };

  const toggleVenue = (name: string) => {
    setVenueNames((current) =>
      current.includes(name)
        ? current.filter((n) => n !== name)
        : [...current, name],
    );
  };

  const toggleInOut = (code: string) => {
    setInOutCodes((current) =>
      current.includes(code)
        ? current.filter((c) => c !== code)
        : [...current, code],
    );
  };

  return (
    <form className="stack" onSubmit={handleSubmit}>
      <div className="row">
        <span className="pill">
          {mode === "create" ? "New saved search" : "Edit saved search"}
        </span>
        {catalog && !catalog.available ? (
          <span className="pill danger">Catalog unavailable</span>
        ) : null}
      </div>

      <InputField
        label="Label"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        required
      />

      <Field
        label="Venues"
        hint="Pick one or more; the booker tries them in order."
      >
        {venueOptions.length === 0 ? (
          <p className="muted">Loading venues…</p>
        ) : (
          <div className="checkbox-row">
            {venueOptions.map((venue) => {
              const selected = venueNames.includes(venue.name);
              return (
                <label
                  key={venue.name}
                  className={`chip ${selected ? "selected" : ""}`.trim()}
                >
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleVenue(venue.name)}
                  />
                  <span>{venue.name}</span>
                </label>
              );
            })}
          </div>
        )}
      </Field>

      <div className="row" style={{ gap: "1rem" }}>
        <Field label="Weekday">
          <select value={weekday} onChange={(e) => setWeekday(e.target.value)}>
            {WEEKDAYS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Hour start">
          <input
            type="number"
            min={minHour}
            max={maxHour - 1}
            value={hourStart}
            onChange={(e) => setHourStart(Number(e.target.value))}
          />
        </Field>
        <Field label="Hour end">
          <input
            type="number"
            min={minHour + 1}
            max={maxHour}
            value={hourEnd}
            onChange={(e) => setHourEnd(Number(e.target.value))}
          />
        </Field>
      </div>

      <Field label="Indoor / outdoor">
        <div className="checkbox-row">
          {(catalog?.in_out_options ?? []).map((option) => {
            const selected = inOutCodes.includes(option.code);
            return (
              <label
                key={option.code}
                className={`chip ${selected ? "selected" : ""}`.trim()}
              >
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => toggleInOut(option.code)}
                />
                <span>{option.label}</span>
              </label>
            );
          })}
        </div>
      </Field>

      <div className="row" style={{ justifyContent: "flex-end" }}>
        {onCancel ? (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
        <Button
          type="submit"
          variant="primary"
          disabled={disabled || venueNames.length === 0}
        >
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

function SavedSearchCard({
  search,
  catalog,
  editing,
  booking,
  checking,
  availability,
  onToggle,
  onDelete,
  onBook,
  onCheckAvailability,
  onDuplicate,
  onClearAvailability,
  onEdit,
  onCancelEdit,
  onEditSubmit,
}: {
  search: SavedSearch;
  catalog: Catalog | null;
  editing: boolean;
  booking: boolean;
  checking: boolean;
  availability: AvailabilityResponse | undefined;
  onToggle: () => void;
  onDelete: () => void;
  onBook: () => void;
  onCheckAvailability: () => void;
  onDuplicate: () => void;
  onClearAvailability: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onEditSubmit: (body: SavedSearchInput) => void | Promise<void>;
}) {
  if (editing) {
    return (
      <GlassCard>
        <SearchForm
          mode="edit"
          catalog={catalog}
          submitLabel="Update search"
          onSubmit={onEditSubmit}
          onCancel={onCancelEdit}
          initial={{
            label: search.label,
            venue_names: search.venue_names,
            weekday: search.weekday,
            hour_start: search.hour_start,
            hour_end: search.hour_end,
            in_out_codes: search.in_out_codes,
          }}
        />
      </GlassCard>
    );
  }

  return (
    <GlassCard>
      <div
        className="row"
        style={{ justifyContent: "space-between", alignItems: "flex-start" }}
      >
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="row">
            <h2 style={{ margin: 0 }}>{search.label}</h2>
            <span className={`pill ${search.is_active ? "positive" : ""}`}>
              {search.is_active ? "Active" : "Paused"}
            </span>
          </div>
          <p className="muted" style={{ margin: "0.3rem 0 0.6rem" }}>
            {search.weekday_label} · {search.hour_start}h –{" "}
            {search.hour_end}h · {search.venue_names.join(", ")}
          </p>
          <p className="muted" style={{ fontSize: "0.85rem" }}>
            Next booking window: <strong>{search.next_date || "?"}</strong>
            {search.in_out_codes.length > 0
              ? ` · ${search.in_out_codes.join(" + ")}`
              : null}
          </p>
        </div>
        <div className="row" style={{ alignItems: "center" }}>
          <Button onClick={onCheckAvailability} disabled={checking}>
            {checking ? "Checking…" : "Check availability"}
          </Button>
          <Button onClick={onEdit}>Edit</Button>
          <Button onClick={onDuplicate}>Duplicate</Button>
          <Button onClick={onToggle}>
            {search.is_active ? "Pause" : "Activate"}
          </Button>
          <Button variant="primary" onClick={onBook} disabled={booking}>
            {booking ? "Booking…" : "Book now"}
          </Button>
          <Button variant="danger" onClick={onDelete}>
            Delete
          </Button>
        </div>
      </div>

      {availability ? (
        <AvailabilityPanel
          availability={availability}
          onClose={onClearAvailability}
        />
      ) : null}
    </GlassCard>
  );
}

function AvailabilityPanel({
  availability,
  onClose,
}: {
  availability: AvailabilityResponse;
  onClose: () => void;
}) {
  const totalSlots = availability.venues.reduce(
    (sum, venue) => sum + venue.slots.length,
    0,
  );
  return (
    <div style={{ marginTop: "1rem" }}>
      <hr className="divider" />
      <div
        className="row"
        style={{ justifyContent: "space-between", alignItems: "center" }}
      >
        <div className="row">
          <span className="pill positive">
            {totalSlots} slot{totalSlots === 1 ? "" : "s"} on {availability.date}
          </span>
          <span className="muted" style={{ fontSize: "0.8rem" }}>
            (anonymous probe — log in to actually book)
          </span>
        </div>
        <Button variant="ghost" onClick={onClose}>
          Hide
        </Button>
      </div>
      <div className="stack" style={{ marginTop: "0.8rem" }}>
        {availability.venues.map((venue) => (
          <div key={venue.name}>
            <h3 style={{ margin: "0 0 0.4rem" }}>{venue.name}</h3>
            {venue.error ? (
              <p className="muted" style={{ color: "var(--paris-red-soft)" }}>
                {venue.error}
              </p>
            ) : venue.slots.length === 0 ? (
              <p className="muted">No slots available right now.</p>
            ) : (
              <ul
                style={{
                  listStyle: "none",
                  padding: 0,
                  margin: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.3rem",
                }}
              >
                {venue.slots.map((slot, index) => (
                  <li
                    key={`${venue.name}-${index}`}
                    style={{ fontSize: "0.9rem" }}
                  >
                    <span className="pill">{slot.hour || "?"}</span>
                    <span style={{ marginLeft: "0.5rem" }}>
                      <strong>{slot.price}</strong>
                      {slot.label ? ` · ${slot.label}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
