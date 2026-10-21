import {
  forwardRef,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { useReducedMotion } from "motion/react";
import type OLMap from "ol/Map";
import "ol/ol.css";
import Icon from "./Icon";
import LayerPopover from "./map/LayerPopover";
import MapToolbar from "./map/MapToolbar";
import { useLayerActions } from "./map/useLayerActions";
import { useMapInteractions } from "./map/useMapInteractions";
import { useRasterController } from "./map/useRasterController";
import { useRasterStyle } from "./map/useRasterStyle";
import type { RasterLayer } from "../types";
import type { InternalLayer, MapHandle, MapPaneProps } from "./map/types";

export type { MapHandle } from "./map/types";
export { parseBounds } from "./map/model";

const MapPane = forwardRef<MapHandle, MapPaneProps>(
  function MapPane(props, ref) {
    const map = useRef<OLMap | null>(null);
    const layers = useRef<InternalLayer[]>([]);
    const selected = useRef<RasterLayer | null>(null);
    const pending = useRef(new Map<string, Promise<void>>());
    const latest = useRef(props);
    latest.current = props;
    const refs = useMemo(() => ({ map, layers, selected, pending }), []);
    const reduced = useReducedMotion();
    const [showLayers, setShowLayers] = useState(true);
    const controller = useRasterController(refs, latest, Boolean(reduced));
    const interactions = useMapInteractions(
      refs,
      latest,
      controller.setPixel,
      reduced,
    );
    const styleRaster = useRasterStyle(
      refs,
      latest,
      controller.palette,
      controller.sync,
    );
    const layerActions = useLayerActions(
      refs,
      controller.select,
      controller.sync,
    );

    useImperativeHandle(
      ref,
      () => ({
        showRaster: controller.showRaster,
        applyEvent: controller.applyEvent,
        clear: controller.clear,
        fitArea: controller.fitArea,
      }),
      [
        controller.showRaster,
        controller.applyEvent,
        controller.clear,
        controller.fitArea,
      ],
    );

    return (
      <section className="map-workspace wb-panel">
        <MapToolbar
          props={props}
          current={controller.current}
          recordCount={controller.records.length}
          drawing={interactions.drawing}
          showLayers={showLayers}
          palette={controller.palette}
          minimum={controller.minimum}
          maximum={controller.maximum}
          onDraw={interactions.drawArea}
          onImport={(file) => void interactions.importArea(file)}
          onFit={controller.fitArea}
          onRestyle={(color) =>
            styleRaster(controller.minimum, controller.maximum, color)
          }
          onPalette={controller.setPalette}
          onMinimum={controller.setMinimum}
          onMaximum={controller.setMaximum}
          onToggleLayers={() => setShowLayers((visible) => !visible)}
        />
        <div className="map" ref={interactions.target}>
          {!controller.records.length && (
            <div className="map-empty">
              <Icon name="layers" />
              <b>暂无图层</b>
              <small>运行脚本，或从任务中显示计算结果</small>
            </div>
          )}
          <LayerPopover
            records={controller.records}
            current={controller.current}
            visible={showLayers}
            onSelect={(record, fit) => controller.select(record, fit)}
            onRemove={layerActions.remove}
            onVisibility={layerActions.setVisible}
          />
          <div className="map-coordinate-bar">
            <span>{interactions.position || "经纬度坐标"}</span>
            {controller.pixel && <span>像素 {controller.pixel}</span>}
          </div>
          <span className="basemap-label">本地坐标网格</span>
        </div>
      </section>
    );
  },
);

export default MapPane;
