import Link from "next/link";
import { notFound } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/errors";
import {
  type DomainProvisioningStatusApiResponse,
  toProvisioningAttemptFromStatus,
} from "../../_lib/provisioning-api";
import { StepLog } from "./_components/step-log";
import type { ProvisioningAttempt } from "@/types/domain";

const providerLabel: Record<string, string> = {
  manual: "Manual",
  cloudflare: "Cloudflare",
  route53: "Route 53",
};

type Props = { params: Promise<{ domainId: string }> };

type DomainDetailApiResponse = {
  id: string;
  name: string;
  dns_provider?: string | null;
};

export default async function ProvisionPage({ params }: Props) {
  const { domainId } = await params;

  let domain: DomainDetailApiResponse;
  try {
    domain = await serverJson<DomainDetailApiResponse>(
      ENDPOINTS.domains.detail(domainId),
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  let attempt: ProvisioningAttempt | null = null;
  try {
    const status = await serverJson<DomainProvisioningStatusApiResponse>(
      ENDPOINTS.domains.provisioningStatus(domainId),
    );
    const mapped = toProvisioningAttemptFromStatus(status, {
      id: domain.id,
      name: domain.name,
      dns_provider: domain.dns_provider ?? null,
    });

    const noAttempt =
      !status.run_id &&
      !status.runId &&
      (status.status === "not_started" || !status.status) &&
      mapped.steps.length === 0;
    attempt = noAttempt ? null : mapped;
  } catch {
    attempt = null;
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="text-sm text-text-muted">
            <Link href="/domains" className="hover:underline">
              Domains
            </Link>{" "}
            /{" "}
            <Link href={`/domains/${domainId}`} className="hover:underline">
              {domain.name}
            </Link>{" "}
            / Provisioning
          </p>
          <h1 className="page-title">Provisioning</h1>
        </div>
        {attempt && (
          <div className="page-actions">
            <Badge variant="outline">
              {providerLabel[attempt.provider] ?? attempt.provider}
            </Badge>
          </div>
        )}
      </header>

      {attempt ? (
        <StepLog initialAttempt={attempt} domainId={domainId} />
      ) : (
        <div className="surface-panel p-6">
          <p className="text-sm text-text-muted">
            No provisioning attempt found for this domain.{" "}
            <Link href={`/domains/${domainId}`} className="hover:underline">
              Return to domain detail.
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}
