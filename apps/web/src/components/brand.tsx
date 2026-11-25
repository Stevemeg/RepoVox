import Link from "next/link";
import { Code2 } from "lucide-react";

export function Brand({ className = "brand" }: { className?: string }) {
  return (
    <Link href="/" className={className} aria-label="RepoVox home">
      <span className="brand-mark" aria-hidden="true">
        <Code2 size={18} />
      </span>
      <span className="brand-text" aria-hidden="true">
        RepoVox
      </span>
    </Link>
  );
}
