import { useState } from "react";
import type {
  BookingRequest,
  BookingRequestCreate,
  Facility,
} from "../api/client";

interface RequestFormProps {
  request?: BookingRequest | null;
  facilities: Facility[];
  onSubmit: (data: BookingRequestCreate) => void;
  onCancel: () => void;
}

const DAYS = [
  { value: 0, label: "Lun", full: "Lundi" },
  { value: 1, label: "Mar", full: "Mardi" },
  { value: 2, label: "Mer", full: "Mercredi" },
  { value: 3, label: "Jeu", full: "Jeudi" },
  { value: 4, label: "Ven", full: "Vendredi" },
  { value: 5, label: "Sam", full: "Samedi" },
  { value: 6, label: "Dim", full: "Dimanche" },
];

const HOURS = Array.from({ length: 15 }, (_, i) => i + 8); // 8:00 to 22:00

export function RequestForm({
  request,
  facilities,
  onSubmit,
  onCancel,
}: RequestFormProps) {
  const [dayOfWeek, setDayOfWeek] = useState(request?.day_of_week ?? 5);
  const [timeStart, setTimeStart] = useState(request?.time_start ?? "18:00");
  const [timeEnd, setTimeEnd] = useState(request?.time_end ?? "20:00");
  const [courtType, setCourtType] = useState(request?.court_type ?? "any");
  const [selectedFacilities, setSelectedFacilities] = useState<string[]>(
    request?.facility_preferences ?? [],
  );
  const [partnerName, setPartnerName] = useState(request?.partner_name ?? "");
  const [partnerEmail, setPartnerEmail] = useState(
    request?.partner_email ?? "",
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      day_of_week: dayOfWeek,
      time_start: timeStart,
      time_end: timeEnd,
      court_type: courtType,
      facility_preferences: selectedFacilities,
      partner_name: partnerName || undefined,
      partner_email: partnerEmail || undefined,
      active: true,
    });
  };

  const toggleFacility = (code: string) => {
    setSelectedFacilities((prev) =>
      prev.includes(code) ? prev.filter((f) => f !== code) : [...prev, code],
    );
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-end sm:items-center justify-center z-50">
      <div className="bg-white w-full sm:w-96 sm:rounded-xl rounded-t-xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-white px-4 py-3 border-b flex items-center justify-between">
          <button onClick={onCancel} className="text-gray-500">
            Annuler
          </button>
          <h2 className="font-semibold">
            {request ? "Modifier" : "Nouvelle alarme"}
          </h2>
          <button
            onClick={handleSubmit}
            className="text-green-600 font-semibold"
          >
            {request ? "Enregistrer" : "Ajouter"}
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-6">
          {/* Day selector */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Jour
            </label>
            <div className="flex flex-wrap gap-2">
              {DAYS.map((day) => (
                <button
                  key={day.value}
                  type="button"
                  onClick={() => setDayOfWeek(day.value)}
                  className={`day-chip ${dayOfWeek === day.value ? "day-chip-selected" : "day-chip-unselected"}`}
                >
                  {day.label}
                </button>
              ))}
            </div>
          </div>

          {/* Time range */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Début
              </label>
              <select
                value={timeStart}
                onChange={(e) => setTimeStart(e.target.value)}
                className="input-field"
              >
                {HOURS.map((h) => (
                  <option key={h} value={`${h.toString().padStart(2, "0")}:00`}>
                    {h}:00
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Fin
              </label>
              <select
                value={timeEnd}
                onChange={(e) => setTimeEnd(e.target.value)}
                className="input-field"
              >
                {HOURS.map((h) => (
                  <option key={h} value={`${h.toString().padStart(2, "0")}:00`}>
                    {h}:00
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Court type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Type de court
            </label>
            <div className="flex gap-2">
              {[
                { value: "any", label: "Tous", icon: "🎾" },
                { value: "indoor", label: "Couvert", icon: "🏠" },
                { value: "outdoor", label: "Découvert", icon: "☀️" },
              ].map((type) => (
                <button
                  key={type.value}
                  type="button"
                  onClick={() => setCourtType(type.value)}
                  className={`flex-1 py-2 px-3 rounded-lg border-2 transition-all ${
                    courtType === type.value
                      ? "border-green-600 bg-green-50"
                      : "border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <span className="block text-lg">{type.icon}</span>
                  <span className="text-sm">{type.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Facilities */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Courts préférés (optionnel)
            </label>
            <div className="max-h-40 overflow-y-auto border rounded-lg p-2 space-y-1">
              {facilities.map((facility) => (
                <label
                  key={facility.code}
                  className="flex items-center gap-2 p-2 hover:bg-gray-50 rounded cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedFacilities.includes(facility.code)}
                    onChange={() => toggleFacility(facility.code)}
                    className="rounded border-gray-300 text-green-600 focus:ring-green-500"
                  />
                  <span className="text-sm">{facility.name}</span>
                </label>
              ))}
            </div>
            {selectedFacilities.length === 0 && (
              <p className="text-xs text-gray-500 mt-1">
                Aucune préférence = tous les courts éligibles
              </p>
            )}
          </div>

          {/* Partner info */}
          <div className="space-y-3">
            <label className="block text-sm font-medium text-gray-700">
              Partenaire (optionnel)
            </label>
            <input
              type="text"
              placeholder="Nom du partenaire"
              value={partnerName}
              onChange={(e) => setPartnerName(e.target.value)}
              className="input-field"
            />
            <input
              type="email"
              placeholder="Email du partenaire"
              value={partnerEmail}
              onChange={(e) => setPartnerEmail(e.target.value)}
              className="input-field"
            />
          </div>
        </form>
      </div>
    </div>
  );
}
