// API Client for RainBot

const API_BASE = "/api";

// Types
export interface LoginCredentials {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface BookingRequest {
  id: string;
  user_id: string;
  day_of_week: number;
  day_of_week_name: string;
  time_start: string;
  time_end: string;
  court_type: string;
  facility_preferences: string[];
  partner_name: string | null;
  partner_email: string | null;
  active: boolean;
}

export interface BookingRequestCreate {
  day_of_week: number;
  time_start: string;
  time_end: string;
  court_type: string;
  facility_preferences: string[];
  partner_name?: string;
  partner_email?: string;
  active: boolean;
}

export interface Booking {
  id: string;
  user_id: string;
  request_id: string;
  facility_name: string;
  facility_code: string;
  court_number: string;
  date: string;
  time_start: string;
  time_end: string;
  partner_name: string | null;
  partner_email: string | null;
  confirmation_id: string | null;
  facility_address: string | null;
  created_at: string | null;
}

export interface Facility {
  code: string;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
}

// Token storage
const TOKEN_KEY = "rainbot_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

// API helpers
async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: { ...headers, ...options.headers },
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearToken();
      window.location.href = "/login";
    }
    const error = await response
      .json()
      .catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || "Request failed");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

// Auth API
export async function login(
  credentials: LoginCredentials,
): Promise<TokenResponse> {
  const response = await apiRequest<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(credentials),
  });
  setToken(response.access_token);
  return response;
}

export function logout(): void {
  clearToken();
  window.location.href = "/login";
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

// Requests API
export async function getRequests(): Promise<BookingRequest[]> {
  return apiRequest<BookingRequest[]>("/requests");
}

export async function createRequest(
  data: BookingRequestCreate,
): Promise<BookingRequest> {
  return apiRequest<BookingRequest>("/requests", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateRequest(
  id: string,
  data: Partial<BookingRequestCreate>,
): Promise<BookingRequest> {
  return apiRequest<BookingRequest>(`/requests/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteRequest(id: string): Promise<void> {
  return apiRequest<void>(`/requests/${id}`, {
    method: "DELETE",
  });
}

// Bookings API
export async function getBookings(): Promise<Booking[]> {
  return apiRequest<Booking[]>("/bookings");
}

export async function getUpcomingBookings(): Promise<Booking[]> {
  return apiRequest<Booking[]>("/bookings/upcoming");
}

// Facilities API
export async function getFacilities(): Promise<Facility[]> {
  return apiRequest<Facility[]>("/facilities");
}
