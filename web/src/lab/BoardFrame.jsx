import { useLayoutEffect, useRef, useState } from "react";
import "./board-frame.css";

export default function BoardFrame({ children, fitKey, minHeight }) {
  const frameRef = useRef(null);
  const hostRef = useRef(null);
  const innerRef = useRef(null);
  const [scale, setScale] = useState(1);

  useLayoutEffect(() => {
    const frame = frameRef.current;
    const host = hostRef.current;
    const inner = innerRef.current;
    if (!frame || !host || !inner) return undefined;
    const fit = () => {
      host.style.width = "auto";
      host.style.height = "auto";
      host.style.overflow = "visible";
      inner.style.transform = "none";
      const width = inner.offsetWidth;
      const height = inner.offsetHeight;
      const style = getComputedStyle(frame);
      const padX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
      const padY = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
      const available = frame.clientWidth - padX;
      const maxHeight = Math.min(window.innerHeight * 0.66, minHeight || 620) - padY;
      if (width < 1 || height < 1 || available < 1 || maxHeight < 1) return;
      const next = Math.min(1, available / width, maxHeight / height);
      host.style.width = `${Math.ceil(width * next)}px`;
      host.style.height = `${Math.ceil(height * next)}px`;
      host.style.overflow = "hidden";
      inner.style.transform = `scale(${next})`;
      setScale((prev) => (prev === next ? prev : next));
    };
    fit();
    const raf = requestAnimationFrame(fit);
    const observer = new ResizeObserver(fit);
    observer.observe(frame);
    window.addEventListener("resize", fit);
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      window.removeEventListener("resize", fit);
    };
  }, [fitKey, minHeight]);

  return (
    <div ref={frameRef} className="lab-board-frame" style={minHeight ? { minHeight: 300 } : undefined}>
      <div ref={hostRef} className="lab-board-host">
        <div ref={innerRef} className="lab-board-inner" style={{ transform: `scale(${scale})` }}>
          {children}
        </div>
      </div>
    </div>
  );
}
