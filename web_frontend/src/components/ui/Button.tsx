import type { ButtonHTMLAttributes, ReactNode } from "react";

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";
type BtnSize = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: BtnVariant;
  size?: BtnSize;
  children: ReactNode;
}

const base =
  "inline-flex items-center justify-center gap-1.5 border-none cursor-pointer font-medium whitespace-nowrap text-ellipsis overflow-hidden shrink-0 rounded-lg transition-[background,border-color] duration-150 disabled:opacity-45 disabled:cursor-not-allowed";

const variantCls: Record<BtnVariant, string> = {
  primary: "bg-primary text-on-primary hover:bg-accent-hover",
  secondary: "bg-primary-container text-fg hover:brightness-[.92]",
  ghost: "bg-transparent text-muted-foreground hover:bg-surface-dim",
  danger: "bg-error text-white hover:brightness-[.92]",
};

const sizeCls: Record<BtnSize, string> = {
  sm: "min-w-8 h-8 text-caption px-3 py-2",
  md: "min-w-10 h-10 px-6 py-3",
  lg: "min-w-12 h-12 text-lg px-6 py-3",
};

export default function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`${base} ${variantCls[variant]} ${sizeCls[size]} ${className}`.trim()}
      {...rest}
    >
      {children}
    </button>
  );
}
