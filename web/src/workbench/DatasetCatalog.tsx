import Icon from "../components/Icon";
import type { Collection } from "../types";

interface Props {
  filteredCollections: Collection[];
  search: string;
  onSearchChange: (value: string) => void;
  selectedCollection: string;
  onSelectCollection: (id: string) => void;
  bbox: string;
  onBboxChange: (value: string) => void;
  start: string;
  onStartChange: (value: string) => void;
  end: string;
  onEndChange: (value: string) => void;
  onInsertCollection: () => void;
  onFitArea: () => void;
}

export default function DatasetCatalog({
  filteredCollections,
  search,
  onSearchChange,
  selectedCollection,
  onSelectCollection,
  bbox,
  onBboxChange,
  start,
  onStartChange,
  end,
  onEndChange,
  onInsertCollection,
  onFitArea,
}: Props) {
  return (
    <div className="library-content catalog-content">
      <div className="library-search">
        <Icon name="search" />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="搜索数据集…"
          aria-label="搜索数据集"
        />
      </div>
      <div className="library-group-title">
        <span>已入库数据</span>
        <small>{filteredCollections.length}</small>
      </div>
      {!filteredCollections.length && (
        <div className="wb-empty">暂无匹配的数据集</div>
      )}
      {filteredCollections.map((collection) => (
        <button
          key={collection.id}
          className={
            "collection" +
            (selectedCollection === collection.id ? " selected" : "")
          }
          onClick={() => onSelectCollection(collection.id)}
        >
          <span className="dataset-icon">
            <Icon name="layers" />
          </span>
          <span>
            <b>{collection.title || collection.id}</b>
            <small>{collection.id}</small>
            <small>
              {(collection["cube:dimensions"]?.bands?.values || []).join(" · ")}
            </small>
          </span>
          <span className="selection-dot" />
        </button>
      ))}
      <div className="aoi-fields">
        <div className="library-group-title">
          <span>研究区与时间</span>
          <button
            className="icon-button"
            onClick={onFitArea}
            aria-label="定位研究区"
          >
            <Icon name="pin" />
          </button>
        </div>
        <label>
          范围<span className="field-unit">W, S, E, N</span>
          <input
            className="coordinates-input"
            value={bbox}
            onChange={(event) => onBboxChange(event.target.value)}
            aria-label="研究区范围"
          />
        </label>
        <div className="date-pair">
          <label>
            开始
            <input
              type="date"
              value={start}
              onChange={(event) => onStartChange(event.target.value)}
              aria-label="开始日期"
            />
          </label>
          <label>
            结束（不含）
            <input
              type="date"
              value={end}
              onChange={(event) => onEndChange(event.target.value)}
              aria-label="结束日期（不含）"
            />
          </label>
        </div>
        <button className="wide insert-button" onClick={onInsertCollection}>
          <Icon name="code" />
          插入数据代码
          <Icon name="arrow" />
        </button>
      </div>
    </div>
  );
}
