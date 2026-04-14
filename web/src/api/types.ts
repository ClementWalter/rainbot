/* Shared API response types — kept narrow and explicit so the React layer
 * stays honest about what the FastAPI contract returns. */

export type User = {
  id: number;
  display_name: string;
  paris_username: string;
  is_admin: boolean;
  is_enabled: boolean;
  created_at: string;
};

export type MeResponse = {
  user: User | null;
  needs_bootstrap: boolean;
};

export type VenueOption = {
  name: string;
  available_now: boolean;
  courts: { id: string; name: string }[];
};

export type InOutOption = {
  code: string;
  label: string;
};

export type Catalog = {
  venues: VenueOption[];
  in_out_options: InOutOption[];
  min_hour: number;
  max_hour: number;
  available: boolean;
};

export type SavedSearch = {
  id: number;
  label: string;
  venue_names: string[];
  weekday: string;
  weekday_label: string;
  hour_start: number;
  hour_end: number;
  in_out_codes: string[];
  is_active: boolean;
  next_date: string;
  created_at: string;
};

export type BookingRecord = {
  id: number;
  user_id: number;
  search_id: number;
  venue_name: string;
  court_id: string;
  equipment_id: string;
  /** Human-readable court name resolved from the catalog (e.g. "Court N°4"). Empty when unknown. */
  court_name: string;
  date_deb: string;
  date_fin: string;
  price_eur: string;
  price_label: string;
  booked_at: string;
};

export type ReservationDetails = {
  venue: string;
  address: string;
  date_label: string;
  hours_label: string;
  court_label: string;
  entry_label: string;
  balance_label: string;
  cancel_deadline: string;
};

export type PendingReservation = {
  has_active_reservation: boolean;
  raw_text: string;
  details: ReservationDetails | null;
};

export type PendingResponse = {
  pending: PendingReservation | null;
  error: string;
};

export type AvailabilitySlot = {
  hour: string;
  price: string;
  label: string;
};

export type AvailabilityVenue = {
  name: string;
  slots: AvailabilitySlot[];
  error: string;
};

export type AvailabilityResponse = {
  date: string;
  venues: AvailabilityVenue[];
};

export type BurstWindow = {
  time: string;
  plus_minus_minutes: number;
  interval_seconds: number;
};

export type SchedulerSettings = {
  enabled: boolean;
  default_interval_seconds: number;
  tick_noise_seconds: number;
  burst_windows: BurstWindow[];
  min_interval_seconds: number;
  max_interval_seconds: number;
  max_tick_noise_seconds: number;
};

export type SchedulerRun = {
  id: number;
  started_at: string;
  finished_at: string;
  summary: Record<string, unknown>;
};

export type SchedulerOverview = {
  settings: SchedulerSettings;
  runs: SchedulerRun[];
};

export type AppSettings = {
  captcha_api_key: string;
};
