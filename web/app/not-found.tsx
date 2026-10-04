import Link from "next/link";
import { container, ctaPrimary } from "@/lib/site";

export default function NotFound() {
  return (
    <div className={`${container} py-20`}>
      <p className="hunk">@@ 404 @@</p>
      <h1 className="mt-2 text-4xl font-extrabold [font-stretch:90%]">Nothing at this ref.</h1>
      <p className="mt-3 max-w-md text-muted-foreground">The page you asked for does not exist. Runs are kept for 30 days.</p>
      <Link href="/forge" className={`${ctaPrimary} mt-8`}>
        Start a new run
      </Link>
    </div>
  );
}
