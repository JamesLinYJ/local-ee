import type { RefObject } from "react";
import type ImageLayer from "ol/layer/Image";
import type ImageStatic from "ol/source/ImageStatic";
import type { Job, MapEvent, RasterLayer } from "../../types";

export type LayerIntent = Extract<MapEvent, { type: "map_layer" }>;

export interface InternalLayer {
  metadata: RasterLayer;
  layer: ImageLayer<ImageStatic>;
}

export interface MapHandle {
  showRaster: (job: Job, name: string, intent?: LayerIntent) => Promise<void>;
  applyEvent: (event: MapEvent, job?: Job) => Promise<void>;
  clear: () => void;
  fitArea: () => void;
}

export interface MapPaneProps {
  bbox: string;
  expanded: boolean;
  onExpand: () => void;
  onBounds: (text: string) => void;
  onSelection: (layer: RasterLayer | null) => void;
  onInspect: (position: string, pixel: string) => void;
  onError: (message: string) => void;
}

export interface MapRefs {
  map: RefObject<import("ol/Map").default | null>;
  layers: RefObject<InternalLayer[]>;
  selected: RefObject<RasterLayer | null>;
  pending: RefObject<Map<string, Promise<void>>>;
}
