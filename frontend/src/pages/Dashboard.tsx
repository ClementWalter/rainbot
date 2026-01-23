import { useState, useEffect } from "react";
import { RequestCard } from "../components/RequestCard";
import { RequestForm } from "../components/RequestForm";
import { BookingList } from "../components/BookingList";
import {
  getRequests,
  getUpcomingBookings,
  getFacilities,
  createRequest,
  updateRequest,
  deleteRequest,
  logout,
  type BookingRequest,
  type Booking,
  type Facility,
  type BookingRequestCreate,
} from "../api/client";

export function Dashboard() {
  const [requests, setRequests] = useState<BookingRequest[]>([]);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingRequest, setEditingRequest] = useState<BookingRequest | null>(
    null,
  );

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [requestsData, bookingsData, facilitiesData] = await Promise.all([
        getRequests(),
        getUpcomingBookings(),
        getFacilities(),
      ]);
      setRequests(requestsData);
      setBookings(bookingsData);
      setFacilities(facilitiesData);
    } catch (err) {
      console.error("Failed to load data:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = async (id: string, active: boolean) => {
    try {
      const updated = await updateRequest(id, { active });
      setRequests((prev) => prev.map((r) => (r.id === id ? updated : r)));
    } catch (err) {
      console.error("Failed to toggle request:", err);
    }
  };

  const handleEdit = (request: BookingRequest) => {
    setEditingRequest(request);
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Supprimer cette alarme ?")) return;
    try {
      await deleteRequest(id);
      setRequests((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      console.error("Failed to delete request:", err);
    }
  };

  const handleSubmit = async (data: BookingRequestCreate) => {
    try {
      if (editingRequest) {
        const updated = await updateRequest(editingRequest.id, data);
        setRequests((prev) =>
          prev.map((r) => (r.id === editingRequest.id ? updated : r)),
        );
      } else {
        const created = await createRequest(data);
        setRequests((prev) => [...prev, created]);
      }
      setShowForm(false);
      setEditingRequest(null);
    } catch (err) {
      console.error("Failed to save request:", err);
    }
  };

  const handleCancel = () => {
    setShowForm(false);
    setEditingRequest(null);
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-2">🎾</div>
          <div className="text-gray-500">Chargement...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-green-600 text-white px-4 py-4 sticky top-0 z-10 shadow-md">
        <div className="max-w-lg mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🎾</span>
            <h1 className="text-xl font-bold">RainBot</h1>
          </div>
          <button
            onClick={logout}
            className="text-green-200 hover:text-white text-sm"
          >
            Déconnexion
          </button>
        </div>
      </header>

      <main className="max-w-lg mx-auto px-4 py-6">
        {/* Requests section */}
        <section className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-900">Mes alarmes</h2>
            <span className="text-sm text-gray-500">
              {requests.filter((r) => r.active).length} active
              {requests.filter((r) => r.active).length !== 1 ? "s" : ""}
            </span>
          </div>

          {requests.length === 0 ? (
            <div className="bg-white rounded-xl p-8 text-center shadow-sm">
              <div className="text-4xl mb-3">🔔</div>
              <p className="text-gray-600 mb-4">
                Créez votre première alarme pour réserver automatiquement un
                court de tennis.
              </p>
            </div>
          ) : (
            <div>
              {requests.map((request) => (
                <RequestCard
                  key={request.id}
                  request={request}
                  onToggle={handleToggle}
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          )}

          {/* Add button */}
          <button
            onClick={() => setShowForm(true)}
            className="btn-primary w-full mt-4 flex items-center justify-center gap-2"
          >
            <span className="text-xl">+</span>
            Nouvelle alarme
          </button>
        </section>

        {/* Upcoming bookings section */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <span className="text-lg">📅</span>
            <h2 className="text-lg font-semibold text-gray-900">
              Prochaines réservations
            </h2>
          </div>
          <BookingList bookings={bookings} />
        </section>
      </main>

      {/* Form modal */}
      {showForm && (
        <RequestForm
          request={editingRequest}
          facilities={facilities}
          onSubmit={handleSubmit}
          onCancel={handleCancel}
        />
      )}
    </div>
  );
}
