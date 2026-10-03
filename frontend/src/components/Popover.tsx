import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

type Props = {
  anchor: HTMLElement;
  children: ReactNode;
  className: string;
  onClose: () => void;
};

export function Popover({ anchor, children, className, onClose }: Props) {
  const panel = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: 0, top: 0, ready: false, above: false });

  useLayoutEffect(() => {
    function place() {
      if (!anchor.isConnected) { onClose(); return; }
      if (!panel.current) return;
      const target = anchor.getBoundingClientRect();
      const viewport = window.visualViewport;
      const originX = viewport?.offsetLeft || 0;
      const originY = viewport?.offsetTop || 0;
      const width = viewport?.width || innerWidth;
      const height = viewport?.height || innerHeight;
      panel.current.style.maxWidth = `${Math.max(0, width - 24)}px`;
      panel.current.style.maxHeight = `${Math.max(0, height - 24)}px`;
      const bounds = panel.current.getBoundingClientRect();
      const above = target.bottom + 8 + bounds.height > originY + height - 12;
      const left = Math.max(originX + 12, Math.min(target.right - bounds.width, originX + width - bounds.width - 12));
      const top = Math.max(originY + 12, Math.min(above ? target.top - bounds.height - 8 : target.bottom + 8, originY + height - bounds.height - 12));
      setPosition((old) => old.left === left && old.top === top && old.ready && old.above === above
        ? old : { left, top, ready: true, above });
    }
    function key(event: KeyboardEvent) { if (event.key === "Escape") onClose(); }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    window.visualViewport?.addEventListener("resize", place);
    window.visualViewport?.addEventListener("scroll", place);
    document.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.visualViewport?.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("scroll", place);
      document.removeEventListener("keydown", key);
    };
  }, [anchor, children, onClose]);

  return createPortal(<div className="popover-layer">
    <div className="popover-backdrop" onClick={onClose} />
    <div ref={panel} className={"popover " + className} data-side={position.above ? "above" : "below"}
      style={{ left: position.left, top: position.top, visibility: position.ready ? "visible" : "hidden" }}>
      {children}
    </div>
  </div>, document.body);
}
