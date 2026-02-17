/**
 * Sortable tile wrapper for edit mode. Uses @dnd-kit/sortable.
 * In edit mode: shows drag handle, remove button, span toggle.
 * In normal mode: renders children only (no extra DOM).
 */

import { type ReactNode } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

interface SortableTileProps {
  id: string;
  colSpan: 1 | 2 | 3;
  onRemove: () => void;
  onToggleSpan: () => void;
  children: ReactNode;
}

const handleStyle: React.CSSProperties = {
  position: "absolute",
  top: 6,
  left: 6,
  width: 28,
  height: 28,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: 6,
  background: "var(--color-bg-secondary)",
  border: "1px solid var(--color-border)",
  color: "var(--color-text-secondary)",
  fontSize: 16,
  cursor: "grab",
  zIndex: 10,
  userSelect: "none",
  touchAction: "none",
};

const removeBtnStyle: React.CSSProperties = {
  position: "absolute",
  top: 6,
  right: 6,
  width: 28,
  height: 28,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: 6,
  background: "var(--color-bg-secondary)",
  border: "1px solid var(--color-border)",
  color: "var(--color-danger, #ef4444)",
  fontSize: 16,
  fontWeight: "bold",
  cursor: "pointer",
  zIndex: 10,
};

const spanBtnStyle: React.CSSProperties = {
  position: "absolute",
  bottom: 6,
  right: 6,
  height: 24,
  padding: "0 8px",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: 4,
  background: "var(--color-bg-secondary)",
  border: "1px solid var(--color-border)",
  color: "var(--color-text-secondary)",
  fontSize: 11,
  fontFamily: "var(--font-body)",
  cursor: "pointer",
  zIndex: 10,
};

export default function SortableTile({
  id,
  colSpan,
  onRemove,
  onToggleSpan,
  children,
}: SortableTileProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    gridColumn: colSpan > 1 ? `span ${colSpan}` : undefined,
    position: "relative",
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 100 : undefined,
  };

  return (
    <div ref={setNodeRef} style={style}>
      {/* Edit mode overlay */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          border: "2px dashed var(--color-accent)",
          borderRadius: "var(--gauge-border-radius, 16px)",
          pointerEvents: "none",
          zIndex: 5,
          opacity: 0.6,
        }}
      />

      {/* Drag handle */}
      <div style={handleStyle} {...attributes} {...listeners}>
        {"\u2630"}
      </div>

      {/* Remove button */}
      <button
        style={removeBtnStyle}
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        aria-label="Remove tile"
      >
        {"\u00D7"}
      </button>

      {/* Span toggle */}
      <button
        style={spanBtnStyle}
        onClick={(e) => {
          e.stopPropagation();
          onToggleSpan();
        }}
        aria-label={`Change tile width (currently ${colSpan}col)`}
      >
        {colSpan === 1 ? "2col \u25B6" : colSpan === 2 ? "3col \u25B6" : "\u25C0 1col"}
      </button>

      {children}
    </div>
  );
}
