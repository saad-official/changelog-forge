import Link from "next/link";

/** `changelog` set in Archivo, `forge` in mono with a diff-gutter plus. */
export function Wordmark() {
  return (
    <Link href="/" className="inline-flex items-baseline gap-1.5 rounded-sm" aria-label="Changelog Forge, home">
      <span aria-hidden="true" className="figure translate-y-[-1px] text-[0.95rem] font-bold text-release-ink">
        +
      </span>
      <span aria-hidden="true" className="font-heading text-[1.05rem] font-extrabold tracking-[-0.03em] [font-stretch:88%]">
        changelog
      </span>
      <span aria-hidden="true" className="figure text-[0.95rem] font-medium text-pencil">
        /forge
      </span>
    </Link>
  );
}
