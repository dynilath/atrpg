/** Tooltip — 即时显示的文本提示气泡。

用法：
  <Tooltip text="解除绑定">
    <button>✕</button>
  </Tooltip>

position 默认 "top"，也支持 "bottom"/"left"/"right"。
*/

import { useState, type ReactNode } from "react";

type Position = "top" | "bottom" | "left" | "right";

interface TooltipProps {
  text: string;
  children: ReactNode;
  position?: Position;
}

const arrowCls: Record<Position, string> = {
  top:    "bottom-0 left-1/2 -translate-x-1/2 translate-y-full border-l-4 border-r-4 border-t-4 border-l-transparent border-r-transparent border-t-fg",
  bottom: "top-0 left-1/2 -translate-x-1/2 -translate-y-full border-l-4 border-r-4 border-b-4 border-l-transparent border-r-transparent border-b-fg",
  left:   "right-0 top-1/2 translate-x-full -translate-y-1/2 border-t-4 border-b-4 border-l-4 border-t-transparent border-b-transparent border-l-fg",
  right:  "left-0 top-1/2 -translate-x-full -translate-y-1/2 border-t-4 border-b-4 border-r-4 border-t-transparent border-b-transparent border-r-fg",
};

const bubbleCls: Record<Position, string> = {
  top:    "bottom-full left-1/2 -translate-x-1/2 mb-2",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
  left:   "right-full top-1/2 -translate-y-1/2 mr-2",
  right:  "left-full top-1/2 -translate-y-1/2 ml-2",
};

export default function Tooltip({ text, children, position = "top" }: TooltipProps) {
  const [show, setShow] = useState(false);

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
    >
      {children}
      {show && (
        <span className={`absolute z-50 ${bubbleCls[position]}`}>
          <span className="block whitespace-nowrap bg-fg text-bg text-caption px-2 py-1 rounded-md shadow-float">
            {text}
          </span>
          <span className={`absolute w-0 h-0 ${arrowCls[position]}`} />
        </span>
      )}
    </span>
  );
}
