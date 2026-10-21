import { useCallback } from "react";
import type { MapRefs } from "./types";

export function useLayerActions(
  refs: MapRefs,
  onSelection: (record: MapRefs["selected"]["current"]) => void,
  sync: () => void,
) {
  const remove = useCallback(
    (id: string) => {
      const entry = refs.layers.current.find(
        (layer) => layer.metadata.id === id,
      );
      if (!entry) return;
      refs.map.current?.removeLayer(entry.layer);
      refs.layers.current = refs.layers.current.filter(
        (layer) => layer !== entry,
      );
      if (refs.selected.current?.id === id) onSelection(null);
      sync();
    },
    [onSelection, refs.layers, refs.map, refs.selected, sync],
  );

  const setVisible = useCallback(
    (id: string, visible: boolean) => {
      const entry = refs.layers.current.find(
        (layer) => layer.metadata.id === id,
      );
      if (!entry) return;
      entry.metadata.visible = visible;
      entry.layer.setVisible(visible);
      sync();
    },
    [refs.layers, sync],
  );

  return { remove, setVisible };
}
