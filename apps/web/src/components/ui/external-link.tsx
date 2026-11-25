import type { ReactNode } from "react";
import type { SafeUrl } from "@/lib/security";

/**
 * The only element in the app that opens another site. It takes a `SafeUrl`, which only
 * the validators in `lib/security.ts` can produce, and always isolates the new tab with
 * `rel="noopener noreferrer"`. ESLint forbids `target` anywhere else.
 */
export function ExternalLink({
  href,
  children,
  className,
}: {
  href: SafeUrl;
  children: ReactNode;
  className?: string;
}) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
      <span className="visually-hidden"> (opens in a new tab)</span>
    </a>
  );
}
