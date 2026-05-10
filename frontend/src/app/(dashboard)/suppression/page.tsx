import { getSession } from "@/lib/auth/session";
import { isAdmin } from "@/lib/auth/guards";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { SuppressionManager } from "./_components/suppression-manager";
import {
  toSuppressionEntry,
  type ApiSuppressionListResponse,
} from "./_lib/suppression-api";

export default async function SuppressionPage() {
  const session = await getSession();
  const adminUser = isAdmin(session);

  if (!adminUser) {
    return (
      <div className="page-stack">
        <header className="page-intro">
          <div className="page-intro-copy">
            <h1 className="page-title">Suppression list</h1>
            <p className="page-description">
              Platform-wide suppression entries. Emails here are excluded from all
              campaign sends. Removals are audited and require justification.
            </p>
          </div>
        </header>

        <div className="surface-panel p-6">
          <p className="text-sm text-text-muted">
            Suppression management is available to admin users only.
          </p>
        </div>
      </div>
    );
  }

  const response = await serverJson<ApiSuppressionListResponse>(ENDPOINTS.suppression.list, {
    query: { limit: 200, offset: 0 },
  });
  const entries = response.items.map(toSuppressionEntry);
  const lastSyncAt = response.items[0]?.first_suppressed_at ?? null;

  return (
    <div className="page-stack">
      <header className="page-intro">
        <div className="page-intro-copy">
          <h1 className="page-title">Suppression list</h1>
          <p className="page-description">
            Platform-wide suppression entries. Emails here are excluded from all
            campaign sends. Removals are audited and require justification.
          </p>
        </div>
      </header>

      <SuppressionManager
        initialEntries={entries}
        syncStatus={{ lastSyncAt, driftCount: 0 }}
        isAdmin
      />
    </div>
  );
}
