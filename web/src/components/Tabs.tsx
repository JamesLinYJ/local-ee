import { useId, useRef } from "react";
import { motion } from "motion/react";
export interface TabItem<T extends string> {
  id: T;
  label: string;
  count?: number;
}
export default function Tabs<T extends string>({
  value,
  onChange,
  tabs,
  label,
  id,
}: {
  value: T;
  onChange: (id: T) => void;
  tabs: TabItem<T>[];
  label: string;
  id: string;
}) {
  const motionId = useId();
  const buttons = useRef(new Map<T, HTMLButtonElement>());
  return (
    <div className="wb-tabs" role="tablist" aria-label={label}>
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          ref={(el) => {
            if (el) buttons.current.set(tab.id, el);
            else buttons.current.delete(tab.id);
          }}
          role="tab"
          id={`${id}-${tab.id}`}
          aria-selected={value === tab.id}
          aria-controls={`${id}-panel-${tab.id}`}
          tabIndex={value === tab.id ? 0 : -1}
          className={value === tab.id ? "active" : ""}
          onClick={() => onChange(tab.id)}
          onKeyDown={(event) => {
            const offset =
              event.key === "ArrowRight"
                ? 1
                : event.key === "ArrowLeft"
                  ? -1
                  : 0;
            const next =
              event.key === "Home"
                ? 0
                : event.key === "End"
                  ? tabs.length - 1
                  : offset
                    ? (index + offset + tabs.length) % tabs.length
                    : -1;
            const target = tabs[next];
            if (target) {
              event.preventDefault();
              onChange(target.id);
              buttons.current.get(target.id)?.focus();
            }
          }}
        >
          {tab.label}
          {tab.count !== undefined && (
            <span className="tab-count">{tab.count}</span>
          )}
          {value === tab.id && (
            <motion.span
              className="react-tab-indicator"
              layoutId={motionId}
              transition={{ type: "spring", stiffness: 500, damping: 38 }}
            />
          )}
        </button>
      ))}
    </div>
  );
}
