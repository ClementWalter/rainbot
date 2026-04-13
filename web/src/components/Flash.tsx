import type { ReactNode } from "react";

type Level = "error" | "success" | "info";

export type FlashMessage = { level: Level; message: string };

// Inline status banner driven by a parent's state (useFlash, below).  Kept
// dumb so pages decide when to clear it (e.g. on next action / navigation).
export function Flash({
  flash,
  onClose,
  children,
}: {
  flash: FlashMessage | null;
  onClose?: () => void;
  children?: ReactNode;
}) {
  if (flash === null && !children) return null;
  const level = flash?.level ?? "info";
  return (
    <div className={`flash ${level}`}>
      <div style={{ flex: 1 }}>{flash?.message ?? children}</div>
      {onClose ? (
        <button
          type="button"
          className="btn btn-ghost btn-icon"
          onClick={onClose}
          aria-label="Dismiss"
        >
          ✕
        </button>
      ) : null}
    </div>
  );
}
