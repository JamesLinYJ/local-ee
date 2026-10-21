import { AnimatePresence, motion } from "motion/react";
import type { RasterLayer } from "../../types";
import Icon from "../Icon";

interface Props {
  records: RasterLayer[];
  current: RasterLayer | null;
  visible: boolean;
  onSelect: (record: RasterLayer, fit?: boolean) => void;
  onRemove: (id: string) => void;
  onVisibility: (id: string, visible: boolean) => void;
}

export default function LayerPopover({
  records,
  current,
  visible,
  onSelect,
  onRemove,
  onVisibility,
}: Props) {
  return (
    <AnimatePresence>
      {visible && (
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
          {!records.length && <div className="wb-empty">暂无可显示图层</div>}
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
                    "layer-row" + (current?.id === record.id ? " selected" : "")
                  }
                >
                  <input
                    type="checkbox"
                    checked={record.visible}
                    aria-label={"显示 " + record.name}
                    onChange={(event) =>
                      onVisibility(record.id, event.target.checked)
                    }
                  />
                  <button
                    className="layer-name"
                    onClick={() => onSelect(record, true)}
                    title={record.name}
                  >
                    {record.name}
                  </button>
                  <button
                    className="icon-button"
                    aria-label={"定位 " + record.name}
                    onClick={() => onSelect(record, true)}
                  >
                    <Icon name="pin" />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={"移除 " + record.name}
                    onClick={() => onRemove(record.id)}
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
  );
}
