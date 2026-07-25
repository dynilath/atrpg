import type { ReactNode, HTMLAttributes } from "react";

type CardVariant = "default" | "interactive" | "flat";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
  title?: string;
  children: ReactNode;
}

const base = "bg-surface border border-border rounded-lg p-5 shadow-card flex-1 min-w-0 overflow-hidden";

const variantCls: Record<CardVariant, string> = {
  default: "",
  interactive:
    "cursor-pointer transition-[border-color,box-shadow] duration-200 px-6 hover:border-muted hover:shadow-card-hover",
  flat: "border-none border-l-[3px] border-l-primary rounded-md px-4 py-3 shadow-none",
};

export default function Card({
  variant = "default",
  title,
  className = "",
  children,
  ...rest
}: CardProps) {
  return (
    <div className={`${base} ${variantCls[variant]} ${className}`.trim()} {...rest}>
      {title && <h3 className="font-heading text-h4 font-heading text-fg mb-2">{title}</h3>}
      {typeof children === "string" ? (
        <p className="text-base text-muted-foreground break-words">{children}</p>
      ) : (
        children
      )}
    </div>
  );
}
