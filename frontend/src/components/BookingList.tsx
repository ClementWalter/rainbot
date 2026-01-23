import type { Booking } from "../api/client";

interface BookingListProps {
  bookings: Booking[];
}

export function BookingList({ bookings }: BookingListProps) {
  if (bookings.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        <p>Aucune réservation à venir</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {bookings.map((booking) => {
        const date = new Date(booking.date);
        const dayNames = ["Dim", "Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"];
        const dayName = dayNames[date.getDay()];
        const dayNum = date.getDate();
        const month = date.toLocaleDateString("fr-FR", { month: "short" });

        return (
          <div
            key={booking.id}
            className="flex items-center gap-3 p-3 bg-white rounded-lg shadow-sm"
          >
            {/* Date badge */}
            <div className="flex-shrink-0 w-14 text-center">
              <div className="text-xs text-gray-500 uppercase">{dayName}</div>
              <div className="text-xl font-bold text-green-600">{dayNum}</div>
              <div className="text-xs text-gray-500">{month}</div>
            </div>

            {/* Booking details */}
            <div className="flex-1 min-w-0">
              <div className="font-medium text-gray-900 truncate">
                {booking.facility_name}
              </div>
              <div className="text-sm text-gray-600">
                Court {booking.court_number} • {booking.time_start}-
                {booking.time_end}
              </div>
              {booking.partner_name && (
                <div className="text-xs text-gray-500">
                  avec {booking.partner_name}
                </div>
              )}
            </div>

            {/* Confirmation badge */}
            {booking.confirmation_id && (
              <div className="flex-shrink-0">
                <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
                  ✓
                </span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
