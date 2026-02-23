/**
 * Dashboard layout context — manages tile arrangement with localStorage
 * persistence. Follows the same pattern as ThemeContext and
 * WeatherBackgroundContext.
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import {
  type DashboardLayout,
  type TilePlacement,
  TILE_REGISTRY,
  DEFAULT_LAYOUT,
  LAYOUT_VERSION,
} from "./tileRegistry.ts";

// --- Types ---

interface DashboardLayoutContextValue {
  layout: DashboardLayout;
  columns: 2 | 3 | 4;
  setColumns: (n: 2 | 3 | 4) => void;
  editMode: boolean;
  setEditMode: (v: boolean) => void;
  reorderTiles: (fromIndex: number, toIndex: number) => void;
  addTile: (tileId: string, colSpan?: 1 | 2) => void;
  removeTile: (tileId: string) => void;
  setTileColSpan: (tileId: string, colSpan: 1 | 2 | 3) => void;
  resetToDefault: () => void;
}

const DashboardLayoutContext =
  createContext<DashboardLayoutContextValue | null>(null);

// --- localStorage helpers ---

const STORAGE_KEY = "davis-wx-dashboard-layout";
const COLUMNS_KEY = "davis-wx-dashboard-columns";

function loadColumns(): 2 | 3 | 4 {
  try {
    const v = parseInt(localStorage.getItem(COLUMNS_KEY) || "3", 10);
    if (v === 2 || v === 3 || v === 4) return v;
  } catch {}
  return 3;
}

function loadLayout(): DashboardLayout {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_LAYOUT;

    const parsed = JSON.parse(raw) as DashboardLayout;

    // Version check — fall back to default if schema changed
    if (parsed.version !== LAYOUT_VERSION) return DEFAULT_LAYOUT;

    // Validate: strip tiles with unknown IDs
    const validTiles = parsed.tiles.filter(
      (t) => t.tileId in TILE_REGISTRY,
    );
    if (validTiles.length === 0) return DEFAULT_LAYOUT;

    return { version: LAYOUT_VERSION, tiles: validTiles };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

function saveLayout(layout: DashboardLayout): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // localStorage may be unavailable
  }
}

// --- Provider ---

export function DashboardLayoutProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [layout, setLayoutState] = useState<DashboardLayout>(loadLayout);
  const [columns, setColumnsState] = useState<2 | 3 | 4>(loadColumns);
  const [editMode, setEditMode] = useState(false);

  const setColumns = useCallback((n: 2 | 3 | 4) => {
    setColumnsState(n);
    try { localStorage.setItem(COLUMNS_KEY, String(n)); } catch {}
  }, []);

  const updateLayout = useCallback((next: DashboardLayout) => {
    setLayoutState(next);
    saveLayout(next);
  }, []);

  const reorderTiles = useCallback(
    (fromIndex: number, toIndex: number) => {
      setLayoutState((prev) => {
        const tiles = [...prev.tiles];
        const [moved] = tiles.splice(fromIndex, 1);
        tiles.splice(toIndex, 0, moved);
        const next = { ...prev, tiles };
        saveLayout(next);
        return next;
      });
    },
    [],
  );

  const addTile = useCallback(
    (tileId: string, colSpan?: 1 | 2) => {
      if (!(tileId in TILE_REGISTRY)) return;
      setLayoutState((prev) => {
        // Prevent duplicates
        if (prev.tiles.some((t) => t.tileId === tileId)) return prev;
        const placement: TilePlacement = { tileId };
        if (colSpan) placement.colSpan = colSpan;
        const next = { ...prev, tiles: [...prev.tiles, placement] };
        saveLayout(next);
        return next;
      });
    },
    [],
  );

  const removeTile = useCallback((tileId: string) => {
    setLayoutState((prev) => {
      const next = {
        ...prev,
        tiles: prev.tiles.filter((t) => t.tileId !== tileId),
      };
      saveLayout(next);
      return next;
    });
  }, []);

  const setTileColSpan = useCallback(
    (tileId: string, colSpan: 1 | 2 | 3) => {
      setLayoutState((prev) => {
        const next = {
          ...prev,
          tiles: prev.tiles.map((t) =>
            t.tileId === tileId ? { ...t, colSpan } : t,
          ),
        };
        saveLayout(next);
        return next;
      });
    },
    [],
  );

  const resetToDefault = useCallback(() => {
    updateLayout(DEFAULT_LAYOUT);
    setEditMode(false);
  }, [updateLayout]);

  return (
    <DashboardLayoutContext.Provider
      value={{
        layout,
        columns,
        setColumns,
        editMode,
        setEditMode,
        reorderTiles,
        addTile,
        removeTile,
        setTileColSpan,
        resetToDefault,
      }}
    >
      {children}
    </DashboardLayoutContext.Provider>
  );
}

// --- Hook ---

export function useDashboardLayout(): DashboardLayoutContextValue {
  const ctx = useContext(DashboardLayoutContext);
  if (!ctx) {
    throw new Error(
      "useDashboardLayout must be used within a DashboardLayoutProvider",
    );
  }
  return ctx;
}
