import type { ReactNode, HTMLAttributes } from "react";

type Props = HTMLAttributes<HTMLDivElement> & { children: ReactNode };

// Glass surfaces all share the same rounded/backdrop treatment; keeping it in
// one component makes styling changes a one-file update.
export function GlassCard({ children, className = "", ...rest }: Props) {
  return (
    <div className={`glass-card ${className}`.trim()} {...rest}>
      {children}
    </div>
  );
}
