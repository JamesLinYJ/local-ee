import type { Extent } from "ol/extent";
import { assetUrl } from "../../lib/api";
import type { RasterLayer, VisParams } from "../../types";

export function parseBounds(text: string): Extent {
  const values = text.split(",").map(Number);
  if (values.length !== 4 || !values.every(Number.isFinite))
    throw new Error("请填写有效的 W,S,E,N 范围");
  const [w, s, e, n] = values as [number, number, number, number];
  if (w >= e || s >= n || w < -180 || e > 180 || s < -90 || n > 90)
    throw new Error("请填写有效的 W,S,E,N 范围");
  return values;
}

export const previewUrl = (
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

export const coordinateLabel = (p: number[]) =>
  `${p[0]!.toFixed(5)}° E / ${p[1]!.toFixed(5)}° N`;
