import type { ReactNode } from "react";

interface NavItem {
  key: string;
  label: string;
  active?: boolean;
  onClick?: () => void;
}

interface NavigationProps {
  brand: ReactNode;
  items: NavItem[];
  user?: ReactNode;
}

export default function Navigation({ brand, items, user }: NavigationProps) {
  return (
    <nav className="flex items-center px-5 py-3 bg-surface-container-low border-b border-border gap-4 w-full box-border">
      <span className="font-heading text-h4 font-heading text-fg whitespace-nowrap">
        {brand}
      </span>
      <ul className="flex items-center gap-3 list-none m-0 p-0">
        {items.map((item) => (
          <li key={item.key}>
            <a
              className={`text-base no-underline px-2 py-1 rounded-sm transition-colors duration-150 whitespace-nowrap cursor-pointer hover:bg-surface-container-high ${
                item.active
                  ? "text-accent font-heading"
                  : "text-muted-foreground"
              }`}
              onClick={item.onClick}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter") item.onClick?.();
              }}
            >
              {item.label}
            </a>
          </li>
        ))}
      </ul>
      {user && <div className="flex items-center gap-2 ml-auto">{user}</div>}
    </nav>
  );
}

export function NavAvatar({ initial }: { initial: string }) {
  return (
    <span className="w-7 h-7 min-w-7 rounded-full bg-accent text-on-primary flex items-center justify-center text-caption font-heading shrink-0">
      {initial}
    </span>
  );
}
