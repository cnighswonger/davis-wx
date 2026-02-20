/**
 * Dashboard grid container. Renders tiles from the layout context.
 * Normal mode: plain CSS grid, zero DnD overhead.
 * Edit mode: DndContext + SortableContext for drag-and-drop reordering.
 */

import { useState, useCallback } from "react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  TouchSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  rectSortingStrategy,
} from "@dnd-kit/sortable";

import { useDashboardLayout } from "./DashboardLayoutContext.tsx";
import { TILE_REGISTRY } from "./tileRegistry.ts";
import TileRenderer from "./TileRenderer.tsx";
import SortableTile from "./SortableTile.tsx";
import TileCatalogModal from "./TileCatalogModal.tsx";
import FlipTile from "../components/common/FlipTile.tsx";
import { useWeatherData } from "../context/WeatherDataContext.tsx";
import { useIsMobile } from "../hooks/useIsMobile.ts";

const gridStyle: React.CSSProperties = {
  display: "grid",
  // Cap at 3 columns: each column is at least 1/3 of available width (minus gaps),
  // but never narrower than 280px so it collapses to 2 or 1 on small screens.
  gridTemplateColumns: "repeat(auto-fill, minmax(max(280px, calc((100% - 32px) / 3)), 1fr))",
  gap: "16px",
};

const editToggleStyle: React.CSSProperties = {
  background: "none",
  border: "1px solid var(--color-border)",
  borderRadius: 6,
  padding: "4px 10px",
  cursor: "pointer",
  fontSize: 14,
  color: "var(--color-text-secondary)",
  fontFamily: "var(--font-body)",
  marginLeft: 12,
  verticalAlign: "middle",
};

const toolbarStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  marginBottom: 12,
  padding: "8px 12px",
  background: "var(--color-bg-card)",
  border: "1px solid var(--color-accent)",
  borderRadius: 8,
  fontSize: 14,
  fontFamily: "var(--font-body)",
};

const toolbarBtnStyle: React.CSSProperties = {
  padding: "6px 16px",
  borderRadius: 6,
  border: "none",
  cursor: "pointer",
  fontSize: 13,
  fontFamily: "var(--font-body)",
  fontWeight: 600,
};

const addTilePlaceholderStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  minHeight: 160,
  border: "2px dashed var(--color-border)",
  borderRadius: "var(--gauge-border-radius, 16px)",
  color: "var(--color-text-muted)",
  fontSize: 16,
  fontFamily: "var(--font-body)",
  cursor: "pointer",
  transition: "border-color 0.2s, color 0.2s",
};

export default function DashboardGrid() {
  const {
    layout,
    editMode,
    setEditMode,
    reorderTiles,
    removeTile,
    setTileColSpan,
    resetToDefault,
  } = useDashboardLayout();
  const { currentConditions } = useWeatherData();
  const isMobile = useIsMobile();
  const [showCatalog, setShowCatalog] = useState(false);

  const hasSolar =
    currentConditions?.solar_radiation != null ||
    currentConditions?.uv_index != null;

  // DnD sensors — only used in edit mode
  const pointerSensor = useSensor(PointerSensor, {
    activationConstraint: { distance: 8 },
  });
  const touchSensor = useSensor(TouchSensor, {
    activationConstraint: { delay: 250, tolerance: 5 },
  });
  const keyboardSensor = useSensor(KeyboardSensor);
  const sensors = useSensors(pointerSensor, touchSensor, keyboardSensor);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldIndex = layout.tiles.findIndex(
        (t) => t.tileId === active.id,
      );
      const newIndex = layout.tiles.findIndex(
        (t) => t.tileId === over.id,
      );
      if (oldIndex !== -1 && newIndex !== -1) {
        reorderTiles(oldIndex, newIndex);
      }
    },
    [layout.tiles, reorderTiles],
  );

  const tileIds = layout.tiles.map((t) => t.tileId);

  // --- Normal mode: plain grid, no DnD ---
  if (!editMode) {
    return (
      <div>
        <h2
          style={{
            margin: "0 0 16px 0",
            fontSize: "24px",
            fontFamily: "var(--font-heading)",
            color: "var(--color-text)",
          }}
        >
          Current Conditions
          <button
            style={editToggleStyle}
            onClick={() => setEditMode(true)}
            aria-label="Edit dashboard layout"
            title="Edit dashboard layout"
          >
            {"\u270E"}
          </button>
        </h2>

        <div className="dashboard-grid" style={gridStyle}>
          {layout.tiles.map((placement) => {
            const def = TILE_REGISTRY[placement.tileId];
            if (!def) return null;
            const colSpan = isMobile ? 1 : (placement.colSpan ?? def.minColSpan);

            const content = <TileRenderer tileId={placement.tileId} />;
            const wrapped = (!isMobile && def.hasFlipTile) ? (
              <FlipTile
                sensor={def.sensor!}
                label={def.chartLabel!}
                unit={def.chartUnit!}
              >
                {content}
              </FlipTile>
            ) : (
              content
            );

            return (
              <div
                key={placement.tileId}
                style={{
                  gridColumn: colSpan > 1 ? `span ${colSpan}` : undefined,
                }}
              >
                {wrapped}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // --- Edit mode: DnD grid ---
  return (
    <div>
      <h2
        style={{
          margin: "0 0 16px 0",
          fontSize: "24px",
          fontFamily: "var(--font-heading)",
          color: "var(--color-text)",
        }}
      >
        Current Conditions
      </h2>

      {/* Edit toolbar */}
      <div className="dashboard-toolbar" style={toolbarStyle}>
        <span style={{ color: "var(--color-accent)", fontWeight: 600 }}>
          Editing Layout
        </span>
        <span style={{ flex: 1 }} />
        <button
          style={{
            ...toolbarBtnStyle,
            background: "var(--color-bg-secondary)",
            color: "var(--color-text)",
            border: "1px solid var(--color-border)",
          }}
          onClick={resetToDefault}
        >
          Reset to Default
        </button>
        <button
          style={{
            ...toolbarBtnStyle,
            background: "var(--color-accent)",
            color: "#fff",
          }}
          onClick={() => setEditMode(false)}
        >
          Done
        </button>
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={tileIds}
          strategy={rectSortingStrategy}
        >
          <div className="dashboard-grid" style={gridStyle}>
            {layout.tiles.map((placement) => {
              const def = TILE_REGISTRY[placement.tileId];
              if (!def) return null;
              const colSpan = isMobile ? 1 : (placement.colSpan ?? def.minColSpan);

              const content = <TileRenderer tileId={placement.tileId} />;
              const wrapped = (!isMobile && def.hasFlipTile) ? (
                <FlipTile
                  sensor={def.sensor!}
                  label={def.chartLabel!}
                  unit={def.chartUnit!}
                  disabled
                >
                  {content}
                </FlipTile>
              ) : (
                content
              );

              return (
                <SortableTile
                  key={placement.tileId}
                  id={placement.tileId}
                  colSpan={colSpan}
                  onRemove={() => removeTile(placement.tileId)}
                  onToggleSpan={() => {
                    const next = colSpan === 1 ? 2 : colSpan === 2 ? 3 : 1;
                    setTileColSpan(placement.tileId, next as 1 | 2 | 3);
                  }}
                >
                  {wrapped}
                </SortableTile>
              );
            })}

            {/* Add tile placeholder */}
            <div
              style={addTilePlaceholderStyle}
              onClick={() => setShowCatalog(true)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") setShowCatalog(true);
              }}
            >
              + Add Tile
            </div>
          </div>
        </SortableContext>
      </DndContext>

      {showCatalog && (
        <TileCatalogModal
          currentTileIds={tileIds}
          hasSolar={hasSolar}
          onClose={() => setShowCatalog(false)}
        />
      )}
    </div>
  );
}
