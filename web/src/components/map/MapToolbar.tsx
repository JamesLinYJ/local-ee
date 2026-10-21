import type { RasterLayer } from "../../types";
import Icon from "../Icon";
import type { MapPaneProps } from "./types";

interface Props {
  props: MapPaneProps;
  current: RasterLayer | null;
  recordCount: number;
  drawing: boolean;
  showLayers: boolean;
  palette: string;
  minimum: string;
  maximum: string;
  onDraw: () => void;
  onImport: (file?: File) => void;
  onFit: () => void;
  onRestyle: (palette?: string) => void;
  onPalette: (value: string) => void;
  onMinimum: (value: string) => void;
  onMaximum: (value: string) => void;
  onToggleLayers: () => void;
}

export default function MapToolbar({
  props,
  current,
  recordCount,
  drawing,
  showLayers,
  palette,
  minimum,
  maximum,
  onDraw,
  onImport,
  onFit,
  onRestyle,
  onPalette,
  onMinimum,
  onMaximum,
  onToggleLayers,
}: Props) {
  return (
    <div className="map-toolbar">
      <div className="map-tools">
        <span className="map-caption">
          <Icon name="map" />
          地图
        </span>
        <button
          className="icon-button"
          onClick={onFit}
          aria-label="定位研究区"
          title="定位研究区"
        >
          <Icon name="pin" />
        </button>
        <button
          onClick={onDraw}
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
              onImport(event.target.files?.[0]);
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
                  onPalette(event.target.value);
                  onRestyle(event.target.value);
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
              onChange={(event) => onMinimum(event.target.value)}
              onBlur={() => onRestyle()}
              onKeyDown={(event) => {
                if (event.key === "Enter") onRestyle();
              }}
              placeholder="自动"
              aria-label="显示最小值"
            />
          </label>
          <label>
            最大
            <input
              value={maximum}
              onChange={(event) => onMaximum(event.target.value)}
              onBlur={() => onRestyle()}
              onKeyDown={(event) => {
                if (event.key === "Enter") onRestyle();
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
          onClick={onToggleLayers}
          className={showLayers ? "active" : ""}
          aria-expanded={showLayers}
        >
          <Icon name="layers" />
          图层<span className="tab-count">{recordCount}</span>
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
  );
}
