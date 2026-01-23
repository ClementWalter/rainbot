import { useState } from "react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Facility } from "../api/client";

// Custom tennis ball icon
const tennisIcon = new L.Icon({
  iconUrl:
    "data:image/svg+xml," +
    encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="28" height="28">
      <circle cx="12" cy="12" r="10" fill="#ccff00" stroke="#9acd32" stroke-width="1.5"/>
      <path d="M 4 12 Q 12 6 20 12" fill="none" stroke="#fff" stroke-width="2"/>
      <path d="M 4 12 Q 12 18 20 12" fill="none" stroke="#fff" stroke-width="2"/>
    </svg>
  `),
  iconSize: [28, 28],
  iconAnchor: [14, 14],
  popupAnchor: [0, -14],
});

interface CourtsMapProps {
  facilities: Facility[];
}

export function CourtsMap({ facilities }: CourtsMapProps) {
  const [search, setSearch] = useState("");

  const filteredFacilities = facilities.filter(
    (f) =>
      f.name.toLowerCase().includes(search.toLowerCase()) ||
      f.address.toLowerCase().includes(search.toLowerCase()),
  );

  // Paris center
  const center: [number, number] = [48.8566, 2.3522];

  return (
    <div className="flex-1 flex flex-col">
      {/* Search bar */}
      <div className="bg-white px-4 py-3 border-b shadow-sm">
        <div className="max-w-4xl mx-auto">
          <input
            type="text"
            placeholder="🔍 Rechercher un court..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent"
          />
          <div className="text-xs text-gray-500 mt-1">
            {filteredFacilities.length} court
            {filteredFacilities.length !== 1 ? "s" : ""}
            {search && " trouvé" + (filteredFacilities.length !== 1 ? "s" : "")}
          </div>
        </div>
      </div>

      {/* Map */}
      <div
        style={{ flex: 1, minHeight: "400px", height: "calc(100vh - 180px)" }}
      >
        <MapContainer
          center={center}
          zoom={12}
          style={{ height: "100%", width: "100%" }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {filteredFacilities.map((facility) => (
            <Marker
              key={facility.code}
              position={[facility.latitude, facility.longitude]}
              icon={tennisIcon}
            >
              <Popup>
                <div className="text-sm min-w-[200px]">
                  <strong className="text-green-700">{facility.name}</strong>
                  <br />
                  <span className="text-gray-600">{facility.address}</span>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>
    </div>
  );
}
