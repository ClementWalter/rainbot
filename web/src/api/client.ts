/* Thin typed fetch wrapper around the FastAPI `/api/*` surface.
 *
 * All requests are same-origin (dev uses the Vite proxy, prod serves the SPA
 * from the FastAPI process itself), so the session cookie rides along without
 * any CORS/credentials gymnastics. */

import type {
  AppSettings,
  AvailabilityResponse,
  BookingRecord,
  BurstWindow,
  Catalog,
  MeResponse,
  PendingResponse,
  SavedSearch,
  SchedulerOverview,
  SchedulerRun,
  SchedulerSettings,
  User,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(
  input: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(input, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...(init.headers ?? {}),
    },
    ...init,
  });
  const isJson = response.headers
    .get("content-type")
    ?.toLowerCase()
    .includes("application/json");
  const payload = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok) {
    const detail =
      (payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : "") || response.statusText;
    throw new ApiError(response.status, detail);
  }
  return payload as T;
}

export const api = {
  me: () => request<MeResponse>("/api/me"),
  login: (paris_username: string, paris_password: string) =>
    request<{ user: User }>("/api/session", {
      method: "POST",
      body: JSON.stringify({ paris_username, paris_password }),
    }),
  logout: () => request<{ ok: true }>("/api/session", { method: "DELETE" }),
  bootstrapAdmin: (body: {
    display_name: string;
    paris_username: string;
    paris_password: string;
  }) =>
    request<{ user: User }>("/api/bootstrap-admin", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  catalog: () => request<Catalog>("/api/catalog"),
  listSearches: () =>
    request<{ searches: SavedSearch[] }>("/api/searches"),
  createSearch: (body: {
    label: string;
    venue_names: string[];
    weekday: string;
    hour_start: number;
    hour_end: number;
    in_out_codes: string[];
  }) =>
    request<{ search: SavedSearch }>("/api/searches", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateSearch: (
    id: number,
    body: {
      is_active?: boolean;
      label?: string;
      venue_names?: string[];
      weekday?: string;
      hour_start?: number;
      hour_end?: number;
      in_out_codes?: string[];
    },
  ) =>
    request<{ search: SavedSearch }>(`/api/searches/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteSearch: (id: number) =>
    request<void>(`/api/searches/${id}`, { method: "DELETE" }),
  bookSearch: (id: number) =>
    request<{ ok: true }>(`/api/searches/${id}/book`, { method: "POST" }),
  checkAvailability: (id: number) =>
    request<AvailabilityResponse>(`/api/searches/${id}/check-availability`, {
      method: "POST",
    }),
  duplicateSearch: (id: number) =>
    request<{ search: SavedSearch }>(`/api/searches/${id}/duplicate`, {
      method: "POST",
    }),
  history: () => request<{ records: BookingRecord[] }>("/api/history"),
  pendingReservation: () =>
    request<PendingResponse>("/api/history/pending"),
  cancelPendingReservation: () =>
    request<{ canceled: boolean }>("/api/history/pending", {
      method: "DELETE",
    }),
  listUsers: () => request<{ users: User[] }>("/api/admin/users"),
  createUser: (body: {
    display_name: string;
    paris_username: string;
    paris_password: string;
    is_admin: boolean;
  }) =>
    request<{ user: User }>("/api/admin/users", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateUser: (
    id: number,
    body: { is_admin?: boolean; is_enabled?: boolean },
  ) =>
    request<{ user: User }>(`/api/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  scheduler: () => request<SchedulerOverview>("/api/admin/scheduler"),
  updateScheduler: (body: {
    enabled?: boolean;
    default_interval_seconds?: number;
    tick_noise_seconds?: number;
    burst_windows?: BurstWindow[];
  }) =>
    request<{ settings: SchedulerSettings }>("/api/admin/scheduler", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  runScheduler: () =>
    request<{ summary: Record<string, unknown> }>(
      "/api/admin/scheduler/run",
      { method: "POST" },
    ),
  schedulerRuns: (limit = 100) =>
    request<{ runs: SchedulerRun[] }>(
      `/api/admin/scheduler/runs?limit=${limit}`,
    ),
  settings: () =>
    request<{ settings: AppSettings }>("/api/admin/settings"),
  updateSettings: (body: { captcha_api_key?: string }) =>
    request<{ settings: AppSettings }>("/api/admin/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
};
