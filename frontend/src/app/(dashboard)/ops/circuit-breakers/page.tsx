import { SectionPanel } from "@/components/patterns/section-panel";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import {
  type BreakerListApiResponse,
  toBreakerEntries,
} from "@/app/(dashboard)/ops/_lib/circuit-breakers-api";
import { BreakerConsole } from "./_components/breaker-console";
import type { BreakerEntry } from "@/types/ops";

export default async function CircuitBreakersPage() {
  let entries: BreakerEntry[] = [];

  try {
    const response = await serverJson<BreakerListApiResponse>(
      ENDPOINTS.circuitBreakers.list,
    );
    entries = toBreakerEntries(response);
  } catch {
    entries = [];
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Circuit breakers</h1>
          <p className="page-description">
            Four-scope breaker matrix. Polls every 10 seconds. Resets require a
            typed justification.
          </p>
        </div>
      </header>

      <SectionPanel>
        <BreakerConsole initialEntries={entries} />
      </SectionPanel>
    </div>
  );
}
