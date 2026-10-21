import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent, KeyboardEvent, RefObject } from "react";
type Kind = "left" | "right" | "top";
export default function useSplitLayout(
  workspace: RefObject<HTMLElement | null>,
) {
  const [size, setSize] = useState({
      left: 244,
      right: 330,
      top: Math.max(260, Math.round(innerHeight * 0.43)),
    }),
    [dragging, setDragging] = useState(false);
  const cleanup = useRef<() => void>(() => {});
  const clamp = useCallback(
    (kind: Kind, value: number) => {
      const width = workspace.current?.clientWidth ?? innerWidth,
        height = workspace.current?.clientHeight ?? innerHeight - 70;
      setSize((previous) => ({
        ...previous,
        [kind]:
          kind === "top"
            ? Math.max(230, Math.min(height - 227, value))
            : kind === "left"
              ? Math.max(185, Math.min(width - previous.right - 320, value))
              : Math.max(250, Math.min(width - previous.left - 320, value)),
      }));
    },
    [workspace],
  );
  useEffect(() => () => cleanup.current(), []);
  useEffect(() => {
    const update = () => clamp("top", size.top);
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [clamp, size.top]);
  const start = (kind: Kind, event: PointerEvent) => {
    if (event.button !== 0) return;
    event.preventDefault();
    cleanup.current();
    setDragging(true);
    const origin = kind === "top" ? event.clientY : event.clientX,
      initial = size[kind];
    const move = (e: globalThis.PointerEvent) =>
      clamp(
        kind,
        initial +
          ((kind === "top" ? e.clientY : e.clientX) - origin) *
            (kind === "right" ? -1 : 1),
      );
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      setDragging(false);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end, { once: true });
    cleanup.current = end;
  };
  const key = (kind: Kind, event: KeyboardEvent) => {
    const sign =
      event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? -1
        : event.key === "ArrowRight" || event.key === "ArrowDown"
          ? 1
          : 0;
    if (sign) {
      event.preventDefault();
      clamp(kind, size[kind] + sign * 16 * (kind === "right" ? -1 : 1));
    }
  };
  return { size, dragging, start, key };
}
