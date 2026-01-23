import type { BotLog } from "../api/client";

interface LogsListProps {
  logs: BotLog[];
  loading: boolean;
  onRefresh: () => void;
}

const levelStyles: Record<string, { icon: string; color: string }> = {
  SUCCESS: { icon: "✅", color: "text-green-600" },
  INFO: { icon: "ℹ️", color: "text-blue-600" },
  WARNING: { icon: "⚠️", color: "text-yellow-600" },
  ERROR: { icon: "❌", color: "text-red-600" },
};

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "A l'instant";
  if (diffMins < 60) return `Il y a ${diffMins} min`;
  if (diffHours < 24) return `Il y a ${diffHours}h`;
  if (diffDays < 7) return `Il y a ${diffDays}j`;

  return date.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function LogsList({ logs, loading, onRefresh }: LogsListProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-gray-500">Chargement des logs...</div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-900">Activite du bot</h2>
        <button
          onClick={onRefresh}
          className="text-sm text-green-600 hover:text-green-700 font-medium"
        >
          Actualiser
        </button>
      </div>

      {logs.length === 0 ? (
        <div className="bg-white rounded-xl p-8 text-center shadow-sm">
          <div className="text-4xl mb-3">📋</div>
          <p className="text-gray-600">
            Aucune activite enregistree pour le moment.
          </p>
          <p className="text-gray-500 text-sm mt-2">
            Les logs apparaitront ici lorsque le bot tentera de reserver des
            courts.
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl shadow-sm overflow-hidden">
          {logs.map((log, index) => {
            const style = levelStyles[log.level] || levelStyles.INFO;
            return (
              <div
                key={log.id}
                className={`px-4 py-3 ${index !== logs.length - 1 ? "border-b border-gray-100" : ""}`}
              >
                <div className="flex items-start gap-3">
                  <span className="text-lg">{style.icon}</span>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-medium ${style.color}`}>
                      {log.message}
                    </p>
                    {log.facility_name && (
                      <p className="text-xs text-gray-500 mt-0.5">
                        {log.facility_name}
                      </p>
                    )}
                    {log.details?.confirmation_id != null && (
                      <p className="text-xs text-green-600 mt-0.5">
                        Confirmation: {String(log.details.confirmation_id)}
                      </p>
                    )}
                  </div>
                  <span className="text-xs text-gray-400 whitespace-nowrap">
                    {formatTimestamp(log.timestamp)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
