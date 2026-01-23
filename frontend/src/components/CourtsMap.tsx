import { useState } from "react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Tennis court data with coordinates
const COURTS = [
  {
    name: "Amandiers",
    code: "2",
    address: "8 rue Louis Delgrès, 75020 Paris",
    lat: 48.83805,
    lng: 2.41041,
  },
  {
    name: "Atlantique",
    code: "12",
    address: "25 allée du Capitaine Dronne, 75015 Paris",
    lat: 48.8656,
    lng: 2.38669,
  },
  {
    name: "Philippe Auguste",
    code: "15",
    address: "108 avenue Philippe Auguste, 75011 Paris",
    lat: 48.83957,
    lng: 2.3174,
  },
  {
    name: "Porte de Bagnolet",
    code: "23",
    address: "72 rue Louis Lumière, 75020 Paris",
    lat: 48.88309,
    lng: 2.28208,
  },
  {
    name: "Candie",
    code: "53",
    address: "11 rue Candie, 75011 Paris",
    lat: 48.89949,
    lng: 2.34235,
  },
  {
    name: "Carnot",
    code: "58",
    address: "26 boulevard Carnot, 75012 Paris",
    lat: 48.90956,
    lng: 2.4202,
  },
  {
    name: "Georges Carpentier",
    code: "60",
    address: "5 Place de Port au Prince, 75013 Paris",
    lat: 48.85138,
    lng: 2.38002,
  },
  {
    name: "Jesse Owens",
    code: "67",
    address: "172 rue Championnet, 75018 Paris",
    lat: 48.84297,
    lng: 2.4128,
  },
  {
    name: "Reims - Asnières",
    code: "79",
    address: "34 boulevard de Reims, 75017 Paris",
    lat: 48.83049,
    lng: 2.36207,
  },
  {
    name: "Courcelles",
    code: "81",
    address: "211 rue de Courcelles, 75017 Paris",
    lat: 48.83336,
    lng: 2.3486,
  },
  {
    name: "Aurelle de Paladines",
    code: "85",
    address: "10 rue Parmentier, 92200 Neuilly sur Seine",
    lat: 48.88919,
    lng: 2.29245,
  },
  {
    name: "Bertrand Dauvin",
    code: "92",
    address: "12 rue René Binet, 75018 Paris",
    lat: 48.84245,
    lng: 2.29457,
  },
  {
    name: "Docteurs Déjerine",
    code: "98",
    address: "32-36 rue des Docteurs Augusta et Jules Déjerine, 75020 Paris",
    lat: 48.85601,
    lng: 2.41219,
  },
  {
    name: "Dunois",
    code: "109",
    address: "70 rue Dunois, 75013 Paris",
    lat: 48.83308,
    lng: 2.36637,
  },
  {
    name: "Elisabeth",
    code: "120",
    address: "7 avenue Paul Appell, 75014 Paris",
    lat: 48.88059,
    lng: 2.37701,
  },
  {
    name: "La Faluère",
    code: "126",
    address: "route de la Pyramide, 75012 Paris",
    lat: 48.82126,
    lng: 2.32885,
  },
  {
    name: "Jandelle",
    code: "155",
    address: "15-17 cité Jandelle, 75019 Paris",
    lat: 48.82059,
    lng: 2.36744,
  },
  {
    name: "Léo Lagrange",
    code: "174",
    address: "68 boulevard Poniatowski, 75012 Paris",
    lat: 48.89688,
    lng: 2.35642,
  },
  {
    name: "Suzanne Lenglen",
    code: "188",
    address: "2 rue Louis Armand, 75015 Paris",
    lat: 48.86736,
    lng: 2.27145,
  },
  {
    name: "Louis Lumière",
    code: "198",
    address: "30 rue Louis Lumière, 75020 Paris",
    lat: 48.8753,
    lng: 2.3798,
  },
  {
    name: "Moureu - Baudricourt",
    code: "218",
    address: "17 avenue Edison, 75013 Paris",
    lat: 48.89493,
    lng: 2.33551,
  },
  {
    name: "René et André Mourlon",
    code: "220",
    address: "19 rue Gaston de Caillavet, 75015 Paris",
    lat: 48.89271,
    lng: 2.39696,
  },
  {
    name: "Croix Nivert",
    code: "233",
    address: "107 rue de la Croix Nivert, 75015 Paris",
    lat: 48.8303,
    lng: 2.45013,
  },
  {
    name: "Edouard Pailleron",
    code: "240",
    address: "24 rue Edouard Pailleron, 75019 Paris",
    lat: 48.85887,
    lng: 2.41172,
  },
  {
    name: "Rigoulot - La Plaine",
    code: "258",
    address: "18 avenue de la Porte de Brancion, 75015 Paris",
    lat: 48.83208,
    lng: 2.39914,
  },
  {
    name: "Poissonniers",
    code: "264",
    address: "2 rue Jean Cocteau, 75018 Paris",
    lat: 48.89891,
    lng: 2.32533,
  },
  {
    name: "Poliveau",
    code: "267",
    address: "39BIS rue de Poliveau, 75005 Paris",
    lat: 48.82766,
    lng: 2.36411,
  },
  {
    name: "Poterne des Peupliers",
    code: "272",
    address: "17 rue Max Jacob, 75013 Paris",
    lat: 48.85363,
    lng: 2.36359,
  },
  {
    name: "Niox",
    code: "273",
    address: "12 quai Saint-Exupéry, 75016 Paris",
    lat: 48.83724,
    lng: 2.26436,
  },
  {
    name: "Château des Rentiers",
    code: "281",
    address: "184 rue du Château des Rentiers, 75013 Paris",
    lat: 48.83877,
    lng: 2.30475,
  },
  {
    name: "Max Rousié",
    code: "293",
    address: "28 rue André Bréchet, 75017 Paris",
    lat: 48.85686,
    lng: 2.39154,
  },
  {
    name: "Paul Barruel",
    code: "302",
    address: "24 rue Paul Barruel, 75015 Paris",
    lat: 48.89972,
    lng: 2.35197,
  },
  {
    name: "Sablonnière",
    code: "303",
    address: "62 rue Cambronne, 75015 Paris",
    lat: 48.83982,
    lng: 2.35771,
  },
  {
    name: "Sept arpents",
    code: "305",
    address: "9 rue des Sept Arpents, 75019 Paris",
    lat: 48.8625,
    lng: 2.41201,
  },
  {
    name: "Thiéré",
    code: "320",
    address: "9t-11 passage Thiéré, 75011 Paris",
    lat: 48.82031,
    lng: 2.35382,
  },
  {
    name: "Alain Mimoun",
    code: "327",
    address: "15 rue de la Nouvelle Calédonie, 75012 Paris",
    lat: 48.87569,
    lng: 2.24347,
  },
  {
    name: "Valeyre",
    code: "330",
    address: "24 rue de Rochechouart, 75009 Paris",
    lat: 48.88891,
    lng: 2.29611,
  },
  {
    name: "Cordelières",
    code: "428",
    address: "35 rue des Cordelières, 75013 Paris",
    lat: 48.8489,
    lng: 2.28493,
  },
  {
    name: "Henry de Montherlant",
    code: "429",
    address: "30-32 Boulevard Lannes, 75016 Paris",
    lat: 48.82653,
    lng: 2.30001,
  },
  {
    name: "Jules Ladoumègue",
    code: "497",
    address: "39 rue des Petits Ponts, 75019 Paris",
    lat: 48.84397,
    lng: 2.30206,
  },
  {
    name: "Puteaux",
    code: "529",
    address: "1 allée des sports, 92800 Puteaux",
    lat: 48.88955,
    lng: 2.39877,
  },
  {
    name: "Neuve Saint Pierre",
    code: "545",
    address: "5-7 rue Neuve-Saint-Pierre, 75004 Paris",
    lat: 48.83265,
    lng: 2.2767,
  },
  {
    name: "Bobigny",
    code: "560",
    address: "40-102 avenue de la Division Leclerc, 93000 Bobigny",
    lat: 48.85377,
    lng: 2.37378,
  },
  {
    name: "Halle Fret",
    code: "567",
    address: "47 rue des Cheminots, 75018 Paris",
    lat: 48.87793,
    lng: 2.34509,
  },
];

// Custom tennis ball icon
const tennisIcon = new L.Icon({
  iconUrl:
    "data:image/svg+xml," +
    encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
      <circle cx="12" cy="12" r="10" fill="#ccff00" stroke="#9acd32" stroke-width="1"/>
      <path d="M 4 12 Q 12 6 20 12" fill="none" stroke="#fff" stroke-width="2"/>
      <path d="M 4 12 Q 12 18 20 12" fill="none" stroke="#fff" stroke-width="2"/>
    </svg>
  `),
  iconSize: [24, 24],
  iconAnchor: [12, 12],
  popupAnchor: [0, -12],
});

interface CourtsMapProps {
  onClose: () => void;
}

export function CourtsMap({ onClose }: CourtsMapProps) {
  const [search, setSearch] = useState("");

  const filteredCourts = COURTS.filter(
    (c) =>
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.address.toLowerCase().includes(search.toLowerCase()),
  );

  // Paris center
  const center: [number, number] = [48.8566, 2.3522];

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-end sm:items-center justify-center z-50">
      <div className="bg-white w-full sm:w-[600px] sm:rounded-xl rounded-t-xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-4 py-3 border-b flex items-center justify-between shrink-0">
          <h2 className="font-semibold">Courts de tennis</h2>
          <button onClick={onClose} className="text-gray-500 text-2xl">
            &times;
          </button>
        </div>

        {/* Search */}
        <div className="px-4 py-2 border-b shrink-0">
          <input
            type="text"
            placeholder="🔍 Rechercher un court..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg text-sm"
          />
        </div>

        {/* Map */}
        <div className="flex-1 min-h-[300px]">
          <MapContainer
            center={center}
            zoom={12}
            style={{ height: "100%", width: "100%" }}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {filteredCourts.map((court) => (
              <Marker
                key={court.code}
                position={[court.lat, court.lng]}
                icon={tennisIcon}
              >
                <Popup>
                  <div className="text-sm">
                    <strong>{court.name}</strong>
                    <br />
                    <span className="text-gray-600">{court.address}</span>
                  </div>
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>

        {/* Court count */}
        <div className="px-4 py-2 border-t text-sm text-gray-500 shrink-0">
          {filteredCourts.length} court{filteredCourts.length !== 1 ? "s" : ""}{" "}
          {search && "trouvé" + (filteredCourts.length !== 1 ? "s" : "")}
        </div>
      </div>
    </div>
  );
}
