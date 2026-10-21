import { useCallback, useState } from "react";
import ImageLayer from "ol/layer/Image";
import ImageStatic from "ol/source/ImageStatic";
import { fromLonLat, transformExtent } from "ol/proj";
import { api, assetUrl, errorMessage } from "../../lib/api";
import type { Job, MapEvent, RasterInfo, RasterLayer } from "../../types";
import { parseBounds, previewUrl } from "./model";
import type { LayerIntent, MapPaneProps, MapRefs } from "./types";

interface LatestProps {
  current: MapPaneProps;
}

export function useRasterController(
  refs: MapRefs,
  latest: LatestProps,
  reduced: boolean,
) {
  const [records, setRecords] = useState<RasterLayer[]>([]);
  const [current, setCurrent] = useState<RasterLayer | null>(null);
  const [minimum, setMinimum] = useState("");
  const [maximum, setMaximum] = useState("");
  const [palette, setPalette] = useState("vegetation");
  const [pixel, setPixel] = useState("");
  const pending = refs.pending.current;

  const sync = useCallback(
    () => setRecords(refs.layers.current.map((x) => ({ ...x.metadata }))),
    [refs.layers],
  );

  const select = useCallback(
    (record: RasterLayer | null, fit = false) => {
      refs.selected.current = record;
      setCurrent(record ? { ...record } : null);
      setMinimum(
        typeof record?.vis?.min === "number" ? String(record.vis.min) : "",
      );
      setMaximum(
        typeof record?.vis?.max === "number" ? String(record.vis.max) : "",
      );
      setPalette(record?.vis?.palette ? "custom" : "vegetation");
      latest.current.onSelection(record);
      if (record && fit)
        refs.map.current
          ?.getView()
          .fit(transformExtent(record.bounds, "EPSG:4326", "EPSG:3857"), {
            padding: [30, 30, 30, 30],
            maxZoom: 17,
            duration: reduced ? 0 : 220,
          });
    },
    [latest, reduced, refs.map, refs.selected],
  );

  const clear = useCallback(() => {
    for (const entry of refs.layers.current)
      refs.map.current?.removeLayer(entry.layer);
    refs.layers.current = [];
    setRecords([]);
    select(null);
    setPixel("");
  }, [refs.layers, refs.map, select]);

  const fitArea = useCallback(() => {
    try {
      refs.map.current
        ?.getView()
        .fit(
          transformExtent(
            parseBounds(latest.current.bbox),
            "EPSG:4326",
            "EPSG:3857",
          ),
          {
            padding: [30, 30, 30, 30],
            maxZoom: 15,
            duration: reduced ? 0 : 220,
          },
        );
    } catch (error) {
      latest.current.onError(errorMessage(error));
    }
  }, [latest, reduced, refs.map]);

  const showRaster = useCallback(
    async (job: Job, name: string, intent?: LayerIntent) => {
      const id = job.id + "/" + name;
      const existing = refs.layers.current.find((x) => x.metadata.id === id);
      if (existing) {
        if (!intent) select(existing.metadata, true);
        return;
      }
      if (pending.has(id)) return pending.get(id);
      const instance = refs.map.current;
      if (!instance) return;
      const task = (async () => {
        const metadata = await api<RasterInfo>(
          assetUrl(job.id, name, "raster"),
        );
        if (refs.map.current !== instance) return;
        const record: RasterLayer = {
          ...metadata,
          id,
          jid: job.id,
          file: name,
          name: intent?.name ?? `${job.title} / ${name}`,
          visible: intent?.shown ?? true,
          vis: intent?.vis_params,
        };
        const source = new ImageStatic({
          url: previewUrl(record, record.vis),
          projection: "EPSG:4326",
          imageExtent: metadata.bounds,
        });
        source.once("imageloaderror", () =>
          latest.current.onError("图层预览加载失败，请检查任务结果或重新登录"),
        );
        const layer = new ImageLayer({
          source,
          opacity: intent?.opacity ?? 1,
          visible: record.visible,
        });
        instance.addLayer(layer);
        refs.layers.current.push({ metadata: record, layer });
        sync();
        select(record, !intent);
      })().finally(() => pending.delete(id));
      pending.set(id, task);
      return task;
    },
    [latest, pending, refs.layers, refs.map, select, sync],
  );

  const applyEvent = useCallback(
    async (event: MapEvent, job?: Job) => {
      if (event.type === "map_clear") clear();
      else if (event.type === "map_layer" && job) {
        const name = Object.keys(job.assets).find((n) => /\.tiff?$/i.test(n));
        if (name) await showRaster(job, name, event);
      } else if (event.type === "map_view") {
        const view = refs.map.current?.getView();
        if (event.bounds)
          view?.fit(transformExtent(event.bounds, "EPSG:4326", "EPSG:3857"), {
            padding: [30, 30, 30, 30],
            maxZoom: event.zoom ?? 16,
          });
        if (event.center) view?.setCenter(fromLonLat(event.center));
        if (event.zoom !== undefined) view?.setZoom(event.zoom);
      }
    },
    [clear, refs.map, showRaster],
  );

  return {
    records,
    current,
    pixel,
    setPixel,
    minimum,
    setMinimum,
    maximum,
    setMaximum,
    palette,
    setPalette,
    sync,
    select,
    clear,
    fitArea,
    showRaster,
    applyEvent,
  };
}
