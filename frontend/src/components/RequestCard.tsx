import { Toggle } from "./Toggle";
import type { BookingRequest } from "../api/client";

interface RequestCardProps {
  request: BookingRequest;
  onToggle: (id: string, active: boolean) => void;
  onEdit: (request: BookingRequest) => void;
  onDelete: (id: string) => void;
}

export function RequestCard({
  request,
  onToggle,
  onEdit,
  onDelete,
}: RequestCardProps) {
  const courtTypeIcon =
    request.court_type === "indoor"
      ? "🏠"
      : request.court_type === "outdoor"
        ? "☀️"
        : "🎾";
  const courtTypeLabel =
    request.court_type === "indoor"
      ? "Couvert"
      : request.court_type === "outdoor"
        ? "Découvert"
        : "Tous";

  const facilitiesDisplay =
    request.facility_preferences.length > 0
      ? request.facility_preferences.slice(0, 2).join(", ") +
        (request.facility_preferences.length > 2 ? "..." : "")
      : "Tous les courts";

  return (
    <div
      className={`request-card ${!request.active ? "request-card-inactive" : ""}`}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1" onClick={() => onEdit(request)}>
          {/* Day and time */}
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`text-lg ${request.active ? "" : "text-gray-500"}`}
            >
              {request.active ? "🔔" : "🔕"}
            </span>
            <span className="font-semibold text-gray-900">
              {request.day_of_week_name} {request.time_start}-{request.time_end}
            </span>
          </div>

          {/* Facilities */}
          <div className="text-sm text-gray-600 mb-1">{facilitiesDisplay}</div>

          {/* Court type and partner */}
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <span>
              {courtTypeIcon} {courtTypeLabel}
            </span>
            {request.partner_name && (
              <>
                <span>•</span>
                <span>👤 {request.partner_name}</span>
              </>
            )}
          </div>
        </div>

        {/* Toggle */}
        <div className="flex items-center gap-2">
          <Toggle
            enabled={request.active}
            onChange={(active) => onToggle(request.id, active)}
          />
        </div>
      </div>

      {/* Delete button (shown on hover for mobile swipe alternative) */}
      <div className="mt-3 pt-3 border-t border-gray-100 flex justify-end">
        <button
          onClick={() => onDelete(request.id)}
          className="text-sm text-red-500 hover:text-red-700 transition-colors"
        >
          Supprimer
        </button>
      </div>
    </div>
  );
}
