import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import OLMap from "ol/Map";
import View from "ol/View";
import Graticule from "ol/layer/Graticule";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import Draw, { createBox } from "ol/interaction/Draw";
import GeoJSON from "ol/format/GeoJSON";
import { Stroke } from "ol/style";
import { fromLonLat, toLonLat, transformExtent } from "ol/proj";
import type { Extent } from "ol/extent";
import { api, assetUrl, errorMessage } from "../../lib/api";
import type { MapPaneProps, MapRefs } from "./types";
import { coordinateLabel, parseBounds } from "./model";

type InteractionRefs = Pick<MapRefs, "map" | "layers" | "selected" | "pending">;

export function useMapInteractions(
  refs: InteractionRefs,
  latest: RefObject<MapPaneProps>,
  setPixel: (value: string) => void,
  reduced: boolean | null,
) {
  const target = useRef<HTMLDivElement>(null);
  const area = useRef(new VectorSource());
  const draw = useRef<Draw | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [position, setPosition] = useState("");

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
    refs.map.current = instance;
    let pointerFrame = 0;
    let querySequence = 0;
    instance.on("pointermove", (event) => {
      cancelAnimationFrame(pointerFrame);
      pointerFrame = requestAnimationFrame(() =>
        setPosition(coordinateLabel(toLonLat(event.coordinate))),
      );
    });
    instance.on("singleclick", (event) => {
      if (draw.current) return;
      const clickTarget = event.originalEvent.target;
      if (
        clickTarget instanceof Element &&
        clickTarget.closest(".layers-popover,button,input,a")
      )
        return;
      const point = toLonLat(event.coordinate);
      const label = coordinateLabel(point);
      const record = refs.selected.current;
      const sequence = ++querySequence;
      latest.current.onInspect(label, "");
      if (!record) return;
      void api<{ values: (number | null)[] | null }>(
        assetUrl(record.jid, record.file, "pixel") +
          "?" +
          new URLSearchParams({ lon: String(point[0]), lat: String(point[1]) }),
      )
        .then((result) => {
          if (
            refs.map.current !== instance ||
            sequence !== querySequence ||
            refs.selected.current?.id !== record.id
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
      refs.map.current = null;
      draw.current = null;
      refs.layers.current = [];
      area.current.clear();
      refs.pending.current.clear();
    };
  }, [latest, refs.map, refs.layers, refs.pending, refs.selected, setPixel]);

  const drawArea = useCallback(() => {
    const instance = refs.map.current;
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
            .map((value) => value.toFixed(6))
            .join(","),
        );
      queueMicrotask(() => {
        instance.removeInteraction(interaction);
        draw.current = null;
        setDrawing(false);
      });
    });
  }, [latest, refs.map]);

  const fitBounds = useCallback(
    (bounds: Extent) =>
      refs.map.current
        ?.getView()
        .fit(transformExtent(bounds, "EPSG:4326", "EPSG:3857"), {
          padding: [30, 30, 30, 30],
          maxZoom: 15,
          duration: reduced ? 0 : 220,
        }),
    [reduced, refs.map],
  );

  const importArea = useCallback(
    async (file?: File) => {
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
        latest.current.onBounds(
          bounds.map((value) => value.toFixed(6)).join(","),
        );
        fitBounds(bounds);
      } catch (error) {
        latest.current.onError(errorMessage(error));
      }
    },
    [fitBounds, latest],
  );

  return { target, drawing, position, drawArea, importArea };
}
