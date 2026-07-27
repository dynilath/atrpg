import type { ReactNode, HTMLAttributes } from "react";

type SidebarSide = "left" | "right";

interface SidebarProps extends HTMLAttributes<HTMLElement> {
  side?: SidebarSide;
  children: ReactNode;
}

export default function Sidebar({
  side = "right",
  children,
  className = "",
  ...rest
}: SidebarProps) {
  const borderCls = side === "left" ? "border-l" : "border-r";
  return (
    <aside
      className={`w-80 min-w-80 bg-surface-container-low flex flex-col ${borderCls} border-border ${className}`.trim()}
      data-sidebar={side}
      {...rest}
    >
      {children}
    </aside>
  );
}

/* ── Section ── */
export function SbSection({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="px-4 pt-4 pb-2 border-t border-border first:border-t-0">
      {title && (
        <div className="text-caption font-semibold text-muted-foreground uppercase tracking-[0.08em] mb-2">
          {title}
        </div>
      )}
      {children}
    </div>
  );
}

/* ── Item ── */
export function SbItem({
  label,
  sub,
  active,
  onClick,
}: {
  label: string;
  sub?: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 cursor-pointer text-base min-w-0 transition-[filter] duration-150 hover:brightness-[.97] ${
        active ? "bg-primary-container text-primary" : "text-fg"
      }`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") onClick?.();
      }}
    >
      <span className="min-w-0 break-all">{label}</span>
      {sub && <span className="text-caption text-muted-foreground shrink-0">{sub}</span>}
    </div>
  );
}

/* ── Detail ── */
export function SbDetail({
  name,
  desc,
  children,
}: {
  name?: string;
  desc?: string;
  children?: ReactNode;
}) {
  return (
    <div className="p-4 flex-1">
      {name && (
        <div className="font-heading text-h4 font-heading text-fg mb-1">{name}</div>
      )}
      {desc && <div className="text-base text-muted-foreground">{desc}</div>}
      {children}
    </div>
  );
}

/* ── Tabs ── */
export function SbTabs({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap border-b border-border px-2">{children}</div>;
}

export function SbTab({
  label,
  active,
  onClick,
}: {
  label: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <div
      className={`px-3 py-2 text-base cursor-pointer border-b-2 whitespace-nowrap transition-[filter] duration-150 hover:brightness-[.97] ${
        active
          ? "text-primary border-primary"
          : "text-muted-foreground border-transparent"
      }`}
      onClick={onClick}
      role="tab"
      aria-selected={active}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") onClick?.();
      }}
    >
      {label}
    </div>
  );
}

/* ── List ── */
export function SbList({ children }: { children: ReactNode }) {
  return <div className="py-2 flex-1 overflow-y-auto">{children}</div>;
}
