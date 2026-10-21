import { useCallback } from "react";
import ImageStatic from "ol/source/ImageStatic";
import type { RasterLayer, VisParams } from "../../types";
import { previewUrl } from "./model";
import type { MapPaneProps, MapRefs } from "./types";

export function useRasterStyle(
  refs: MapRefs,
  latest: { current: MapPaneProps },
  palette: string,
  sync: () => void,
) {
  return useCallback(
    (minimum: string, maximum: string, color = palette) => {
      const entry = refs.layers.current.find(
        (layer) => layer.metadata.id === refs.selected.current?.id,
      );
      if (!entry) return;
      const vis: VisParams = { ...entry.metadata.vis };
      if (color !== "custom") delete vis.palette;
      if (minimum === "") delete vis.min;
      else vis.min = Number(minimum);
      if (maximum === "") delete vis.max;
      else vis.max = Number(maximum);
      if (
        (typeof vis.min === "number" && !Number.isFinite(vis.min)) ||
        (typeof vis.max === "number" && !Number.isFinite(vis.max)) ||
        (typeof vis.min === "number" &&
          typeof vis.max === "number" &&
          vis.min > vis.max)
      ) {
        latest.current.onError("请输入有效的显示范围，最大值不能小于最小值");
        return;
      }
      entry.metadata.vis = vis;
      entry.layer.setSource(
        new ImageStatic({
          url: previewUrl(entry.metadata, vis, color),
          projection: "EPSG:4326",
          imageExtent: entry.metadata.bounds,
        }),
      );
      sync();
    },
    [latest, palette, refs.layers, refs.selected, sync],
  );
}

export function layerHasSingleBand(record: RasterLayer | null) {
  return record?.bands === 1;
}
