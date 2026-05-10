import { SectionPanel } from "@/components/patterns/section-panel";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { toProvisioningAttempts } from "@/app/(dashboard)/domains/_lib/provisioning-api";
import { ProvisioningAudit } from "./_components/provisioning-audit";
import type { ProvisioningAttempt } from "@/types/domain";

export default async function ProvisioningAuditPage() {
  let attempts: ProvisioningAttempt[] = [];

  try {
    const response = await serverJson<unknown>(ENDPOINTS.ops.provisioning);
    attempts = toProvisioningAttempts(response);
  } catch {
    attempts = [];
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Provisioning</h1>
          <p className="page-description">
            Audit log for all automated domain provisioning attempts.
          </p>
        </div>
      </header>

      <SectionPanel>
        <ProvisioningAudit attempts={attempts} />
      </SectionPanel>
    </div>
  );
}
