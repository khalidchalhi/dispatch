import Link from "next/link";
import { SectionPanel } from "@/components/patterns/section-panel";
import type { WarmingDomainRow } from "@/app/(dashboard)/domains/_lib/warmup-queries";

function MiniProgressBar({ pct }: { pct: number }) {
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`${pct}% through warmup`}
      className="h-1.5 w-24 overflow-hidden rounded-full bg-border"
    >
      <div
        className="h-full rounded-full bg-primary"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

type WarmingDomainsProps = {
  domains: WarmingDomainRow[];
};

export function WarmingDomains({ domains }: WarmingDomainsProps) {
  if (domains.length === 0) {
    return (
      <SectionPanel title="Domains in warmup">
        <p className="text-sm text-text-muted">No domains currently in warmup.</p>
      </SectionPanel>
    );
  }

  return (
    <SectionPanel title="Domains in warmup">
      <div className="grid gap-3">
        {domains.map((d) => {
          const isOverpacing = d.todaySends > d.todayCap;
          return (
            <div
              key={d.id}
              className="flex items-center justify-between gap-4 rounded-md border border-border px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <Link
                  href={`/domains/${d.id}?tab=warmup`}
                  className="truncate text-sm font-medium hover:underline"
                >
                  {d.name}
                </Link>
                <p className="mt-0.5 text-xs text-text-muted">
                  Day {d.currentDay === 0 ? "—" : d.currentDay} of {d.totalDays}
                </p>
              </div>

              <div className="flex items-center gap-4 text-xs text-text-muted">
                <div className="flex flex-col items-end gap-1">
                  <MiniProgressBar pct={d.pctComplete} />
                  <span>{d.pctComplete}%</span>
                </div>
                <div className="text-right">
                  <p>
                    <span
                      className={
                        isOverpacing ? "font-medium text-danger" : "font-medium"
                      }
                    >
                      {d.todaySends.toLocaleString()}
                    </span>
                    {" / "}
                    {d.todayCap.toLocaleString()}
                  </p>
                  <p className="text-text-muted">warmup today</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </SectionPanel>
  );
}
