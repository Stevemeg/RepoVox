import type { ReactNode } from "react";
import { Box } from "lucide-react";

/** An empty collection, with what to do next. */
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <Box size={28} aria-hidden="true" />
      <h3>{title}</h3>
      <p>{description}</p>
      {action && <div className="actions">{action}</div>}
    </div>
  );
}

/** Placeholder rows while records load. Decorative: the region carries `aria-busy`. */
export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="skeleton-stack" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <span className="skeleton" key={index} />
      ))}
    </div>
  );
}
