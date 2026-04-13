import type { ButtonHTMLAttributes, ReactNode } from "react";

// Visual variants map to CSS classes so a designer/operator can tweak them
// globally in theme.css without touching component code.
type Variant = "default" | "primary" | "ghost" | "danger";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  children: ReactNode;
};

export function Button({
  variant = "default",
  className = "",
  children,
  ...rest
}: Props) {
  const variantClass =
    variant === "primary"
      ? "btn-primary"
      : variant === "ghost"
        ? "btn-ghost"
        : variant === "danger"
          ? "btn-danger"
          : "";
  return (
    <button className={`btn ${variantClass} ${className}`.trim()} {...rest}>
      {children}
    </button>
  );
}
