import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import OLMap from "ol/Map";
import View from "ol/View";
import Graticule from "ol/layer/Graticule";
import ImageLayer from "ol/layer/Image";
import ImageStatic from "ol/source/ImageStatic";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import Draw, { createBox } from "ol/interaction/Draw";
import GeoJSON from "ol/format/GeoJSON";
import { Stroke } from "ol/style";
import { fromLonLat, toLonLat, transformExtent } from "ol/proj";
import type { Extent } from "ol/extent";
import "ol/ol.css";
import Icon from "./Icon";
import { api, assetUrl, errorMessage } from "../lib/api";
import type {
  Job,
  MapEvent,
  RasterInfo,
  RasterLayer,
  VisParams,
} from "../types";
type LayerIntent = Extract<MapEvent, { type: "map_layer" }>;
interface InternalLayer {
  metadata: RasterLayer;
  layer: ImageLayer<ImageStatic>;
}
export interface MapHandle {
  showRaster: (job: Job, name: string, intent?: LayerIntent) => Promise<void>;
  applyEvent: (event: MapEvent, job?: Job) => Promise<void>;
  clear: () => void;
  fitArea: () => void;
}
interface Props {
  bbox: string;
  expanded: boolean;
  onExpand: () => void;
  onBounds: (text: string) => void;
  onSelection: (layer: RasterLayer | null) => void;
  onInspect: (position: string, pixel: string) => void;
  onError: (message: string) => void;
}
export function parseBounds(text: string): Extent {
  const values = text.split(",").map(Number);
  if (values.length !== 4 || !values.every(Number.isFinite))
    throw new Error("请填写有效的 W,S,E,N 范围");
  const [w, s, e, n] = values as [number, number, number, number];
  if (w >= e || s >= n || w < -180 || e > 180 || s < -90 || n > 90)
    throw new Error("请填写有效的 W,S,E,N 范围");
  return values;
}
const previewUrl = (
  layer: Pick<RasterLayer, "jid" | "file">,
  vis?: VisParams,
  palette = "vegetation",
) =>
  assetUrl(layer.jid, layer.file, "preview") +
  "?" +
  new URLSearchParams({
    palette,
    ...(vis ? { vis: JSON.stringify(vis) } : {}),
  });
const coordinateLabel = (p: number[]) =>
  `${p[0]!.toFixed(5)}° E / ${p[1]!.toFixed(5)}° N`;
const MapPane = forwardRef<MapHandle, Props>(function MapPane(props, ref) {
  const target = useRef<HTMLDivElement>(null),
    map = useRef<OLMap | null>(null),
    area = useRef(new VectorSource()),
    draw = useRef<Draw | null>(null),
    layers = useRef<InternalLayer[]>([]),
    selected = useRef<RasterLayer | null>(null),
    pending = useRef(new Map<string, Promise<void>>()),
    latest = useRef(props);
  latest.current = props;
  const [records, setRecords] = useState<RasterLayer[]>([]),
    [current, setCurrent] = useState<RasterLayer | null>(null),
    [position, setPosition] = useState(""),
    [pixel, setPixel] = useState(""),
    [drawing, setDrawing] = useState(false),
    [showLayers, setShowLayers] = useState(true),
    [palette, setPalette] = useState("vegetation"),
    [minimum, setMinimum] = useState(""),
    [maximum, setMaximum] = useState("");
  const reduced = useReducedMotion();
  const sync = useCallback(
    () => setRecords(layers.current.map((x) => ({ ...x.metadata }))),
    [],
  );
  const select = useCallback(
    (record: RasterLayer | null, fit = false) => {
      selected.current = record;
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
        map.current
          ?.getView()
          .fit(transformExtent(record.bounds, "EPSG:4326", "EPSG:3857"), {
            padding: [30, 30, 30, 30],
            maxZoom: 17,
            duration: reduced ? 0 : 220,
          });
    },
    [reduced],
  );
  const clear = useCallback(() => {
    for (const entry of layers.current) map.current?.removeLayer(entry.layer);
    layers.current = [];
    setRecords([]);
    select(null);
    setPixel("");
  }, [select]);
  const fitArea = useCallback(() => {
    try {
      map.current
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
  }, [reduced]);
  const showRaster = useCallback(
    async (job: Job, name: string, intent?: LayerIntent) => {
      const id = job.id + "/" + name;
      const existing = layers.current.find((x) => x.metadata.id === id);
      if (existing) {
        if (!intent) select(existing.metadata, true);
        return;
      }
      if (pending.current.has(id)) return pending.current.get(id);
      const instance = map.current;
      if (!instance) return;
      const task = (async () => {
        const metadata = await api<RasterInfo>(
          assetUrl(job.id, name, "raster"),
        );
        if (map.current !== instance) return;
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
        layers.current.push({ metadata: record, layer });
        sync();
        select(record, !intent);
      })().finally(() => pending.current.delete(id));
      pending.current.set(id, task);
      return task;
    },
    [select, sync],
  );
  const applyEvent = useCallback(
    async (event: MapEvent, job?: Job) => {
      if (event.type === "map_clear") clear();
      else if (event.type === "map_layer" && job) {
        const name = Object.keys(job.assets).find((n) => /\.tiff?$/i.test(n));
        if (name) await showRaster(job, name, event);
      } else if (event.type === "map_view") {
        const view = map.current?.getView();
        if (event.bounds)
          view?.fit(transformExtent(event.bounds, "EPSG:4326", "EPSG:3857"), {
            padding: [30, 30, 30, 30],
            maxZoom: event.zoom ?? 16,
          });
        if (event.center) view?.setCenter(fromLonLat(event.center));
        if (event.zoom !== undefined) view?.setZoom(event.zoom);
      }
    },
    [clear, showRaster],
  );
  useImperativeHandle(ref, () => ({ showRaster, applyEvent, clear, fitArea }), [
    showRaster,
    applyEvent,
    clear,
    fitArea,
  ]);
  useEffect(() => {
    if (!target.current) return;
    const instance = new OLMap({
      target: target.current,
      layers: [
        new Graticule({
          strokeStyle: new Stroke({
            color: "#c7d4d5",
            width: 1,
            lineDash: [3, 5],
          }),
          showLabels: true,
          wrapX: false,
        }),
        new VectorLayer({ source: area.current }),
      ],
      view: new View({ center: fromLonLat([113.56, 22.31]), zoom: 13 }),
    });
    map.current = instance;
    let pointerFrame = 0,
      querySequence = 0;
    instance.on("pointermove", (event) => {
      cancelAnimationFrame(pointerFrame);
      pointerFrame = requestAnimationFrame(() =>
        setPosition(coordinateLabel(toLonLat(event.coordinate))),
      );
    });
    instance.on("singleclick", (event) => {
      if (draw.current) return;
      const target = event.originalEvent.target;
      if (
        target instanceof Element &&
        target.closest(".layers-popover,button,input,a")
      )
        return;
      const p = toLonLat(event.coordinate),
        label = coordinateLabel(p),
        record = selected.current,
        sequence = ++querySequence;
      latest.current.onInspect(label, "");
      if (!record) return;
      void api<{ values: (number | null)[] | null }>(
        assetUrl(record.jid, record.file, "pixel") +
          "?" +
          new URLSearchParams({ lon: String(p[0]), lat: String(p[1]) }),
      )
        .then((result) => {
          if (
            map.current !== instance ||
            sequence !== querySequence ||
            selected.current?.id !== record.id
          )
            return;
          const text = result.values
            ? JSON.stringify(result.values)
            : "范围外 / 缺测";
          setPixel(text);
          latest.current.onInspect(label, text);
        })
        .catch((error) => latest.current.onError(errorMessage(error)));
    });
    const observer = new ResizeObserver(() => instance.updateSize());
    observer.observe(target.current);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(pointerFrame);
      instance.setTarget(undefined);
      map.current = null;
      draw.current = null;
      layers.current = [];
      pending.current.clear();
    };
  }, []);
  const drawArea = () => {
    const instance = map.current;
    if (!instance) return;
    if (draw.current) {
      instance.removeInteraction(draw.current);
      draw.current = null;
      setDrawing(false);
      return;
    }
    area.current.clear();
    const interaction = new Draw({
      source: area.current,
      type: "Circle",
      geometryFunction: createBox(),
    });
    draw.current = interaction;
    instance.addInteraction(interaction);
    setDrawing(true);
    interaction.on("drawend", (event) => {
      const extent = event.feature.getGeometry()?.getExtent();
      if (extent)
        latest.current.onBounds(
          transformExtent(extent, "EPSG:3857", "EPSG:4326")
            .map((x) => x.toFixed(6))
            .join(","),
        );
      queueMicrotask(() => {
        instance.removeInteraction(interaction);
        draw.current = null;
        setDrawing(false);
      });
    });
  };
  const importArea = async (file?: File) => {
    if (!file) return;
    try {
      if (file.size > 1000000) throw new Error("GeoJSON 最大 1 MB");
      const data: unknown = JSON.parse(await file.text());
      if (!data || typeof data !== "object") throw new Error("无效 GeoJSON");
      const features = new GeoJSON().readFeatures(data, {
        featureProjection: "EPSG:3857",
      });
      if (!features.length) throw new Error("GeoJSON 没有几何要素");
      area.current.clear();
      area.current.addFeatures(features);
      const extent = area.current.getExtent();
      if (!extent) throw new Error("GeoJSON 没有有效范围");
      const bounds = transformExtent(extent, "EPSG:3857", "EPSG:4326");
      parseBounds(bounds.join(","));
      latest.current.onBounds(bounds.map((x) => x.toFixed(6)).join(","));
      instanceFit(bounds);
    } catch (error) {
      latest.current.onError(errorMessage(error));
    }
  };
  const instanceFit = (bounds: Extent) =>
    map.current
      ?.getView()
      .fit(transformExtent(bounds, "EPSG:4326", "EPSG:3857"), {
        padding: [30, 30, 30, 30],
        maxZoom: 15,
        duration: reduced ? 0 : 220,
      });
  const restyle = (color = palette) => {
    const entry = layers.current.find(
      (x) => x.metadata.id === selected.current?.id,
    );
    if (!entry) return;
    const vis = { ...entry.metadata.vis };
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
  };
  const remove = (id: string) => {
    const entry = layers.current.find((x) => x.metadata.id === id);
    if (!entry) return;
    map.current?.removeLayer(entry.layer);
    layers.current = layers.current.filter((x) => x !== entry);
    if (selected.current?.id === id) select(null);
    sync();
  };
  return (
    <section className="map-workspace wb-panel">
      <div className="map-toolbar">
        <div className="map-tools">
          <span className="map-caption">
            <Icon name="map" />
            地图
          </span>
          <button
            className="icon-button"
            onClick={fitArea}
            aria-label="定位研究区"
            title="定位研究区"
          >
            <Icon name="pin" />
          </button>
          <button
            onClick={drawArea}
            className={drawing ? "active" : ""}
            title="绘制研究区"
          >
            <Icon name="region" />
            <span>绘制</span>
          </button>
          <label className="file-button">
            <Icon name="upload" />
            <span>GeoJSON</span>
            <input
              type="file"
              accept=".json,.geojson"
              hidden
              onChange={(event) => {
                void importArea(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
          </label>
        </div>
        {current && (
          <div className="raster-style">
            {current.bands === 1 && (
              <label>
                色带
                <select
                  value={palette}
                  onChange={(event) => {
                    setPalette(event.target.value);
                    restyle(event.target.value);
                  }}
                  aria-label="色带"
                >
                  {current.vis?.palette && (
                    <option value="custom">脚本色带</option>
                  )}
                  <option value="vegetation">植被</option>
                  <option value="water">水体</option>
                  <option value="gray">灰度</option>
                </select>
              </label>
            )}
            <label>
              最小
              <input
                value={minimum}
                onChange={(event) => setMinimum(event.target.value)}
                onBlur={() => restyle()}
                onKeyDown={(event) => {
                  if (event.key === "Enter") restyle();
                }}
                placeholder="自动"
                aria-label="显示最小值"
              />
            </label>
            <label>
              最大
              <input
                value={maximum}
                onChange={(event) => setMaximum(event.target.value)}
                onBlur={() => restyle()}
                onKeyDown={(event) => {
                  if (event.key === "Enter") restyle();
                }}
                placeholder="自动"
                aria-label="显示最大值"
              />
            </label>
          </div>
        )}
        <div className="map-tools map-tools-right">
          <span className="projection-label">EPSG:4326</span>
          <button
            onClick={() => setShowLayers(!showLayers)}
            className={showLayers ? "active" : ""}
            aria-expanded={showLayers}
          >
            <Icon name="layers" />
            图层<span className="tab-count">{records.length}</span>
          </button>
          <button
            onClick={props.onExpand}
            className="icon-button"
            aria-label={props.expanded ? "退出地图最大化" : "最大化地图"}
            title={props.expanded ? "还原" : "最大化地图"}
          >
            <span className="maximize-icon">{props.expanded ? "⊡" : "⛶"}</span>
          </button>
        </div>
      </div>
      <div className="map" ref={target}>
        {!records.length && (
          <div className="map-empty">
            <Icon name="layers" />
            <b>暂无图层</b>
            <small>运行脚本，或从任务中显示计算结果</small>
          </div>
        )}
        <AnimatePresence>
          {showLayers && (
            <motion.div
              className="layers-popover"
              initial={{ opacity: 0, y: -5, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -5, scale: 0.98 }}
              transition={{ duration: 0.18 }}
            >
              <div className="layers-heading">
                图层<span>{records.length}</span>
              </div>
              {!records.length && (
                <div className="wb-empty">暂无可显示图层</div>
              )}
              <div className="layer-items">
                <AnimatePresence initial={false}>
                  {records.map((record) => (
                    <motion.div
                      layout
                      key={record.id}
                      initial={{ opacity: 0, x: 7 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: 7 }}
                      className={
                        "layer-row" +
                        (current?.id === record.id ? " selected" : "")
                      }
                    >
                      <input
                        type="checkbox"
                        checked={record.visible}
                        aria-label={"显示 " + record.name}
                        onChange={(event) => {
                          const entry = layers.current.find(
                            (x) => x.metadata.id === record.id,
                          );
                          if (entry) {
                            entry.metadata.visible = event.target.checked;
                            entry.layer.setVisible(event.target.checked);
                            sync();
                          }
                        }}
                      />
                      <button
                        className="layer-name"
                        onClick={() => select(record, true)}
                        title={record.name}
                      >
                        {record.name}
                      </button>
                      <button
                        className="icon-button"
                        aria-label={"定位 " + record.name}
                        onClick={() => select(record, true)}
                      >
                        <Icon name="pin" />
                      </button>
                      <button
                        className="icon-button"
                        aria-label={"移除 " + record.name}
                        onClick={() => remove(record.id)}
                      >
                        <Icon name="x" />
                      </button>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div className="map-coordinate-bar">
          <span>{position || "经纬度坐标"}</span>
          {pixel && <span>像素 {pixel}</span>}
        </div>
        <span className="basemap-label">本地坐标网格</span>
      </div>
    </section>
  );
});
export default MapPane;
