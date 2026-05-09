import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageIntro } from "@/components/patterns/page-intro";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import type { DomainListItem, DomainStatus } from "@/types/domain";
import { DomainsTable } from "./_components/domains-table";

type DomainsListApiResponse = {
  items: Array<{
    id: string;
    name: string;
    verification_status: string;
    reputation_status: string;
    updated_at: string;
  }>;
};

function toDomainStatus(
  verificationStatus: string,
  reputationStatus: string,
): DomainStatus {
  if (reputationStatus === "retired") return "retired";
  if (reputationStatus === "burnt") return "burnt";
  if (reputationStatus === "cooling") return "cooling";
  if (verificationStatus === "verified") return "verified";
  if (verificationStatus === "pending") return "pending";
  return "verifying";
}

function toDomainListItem(
  item: DomainsListApiResponse["items"][number],
): DomainListItem {
  return {
    id: item.id,
    name: item.name,
    status: toDomainStatus(item.verification_status, item.reputation_status),
    breaker: "closed",
    updatedAt: item.updated_at,
  };
}

export default async function DomainsPage() {
  const response = await serverJson<DomainsListApiResponse>(
    ENDPOINTS.domains.list,
  );
  const initialDomains = response.items.map(toDomainListItem);

  return (
    <div className="page-stack">
      <PageIntro
        title="Domains"
        description="Add sending domains, set up DNS records, verify ownership, and manage domain lifecycle."
        actions={
          <Button asChild>
            <Link href="/domains/new">
              <Plus className="h-4 w-4" aria-hidden />
              Add domain
            </Link>
          </Button>
        }
      />
      <DomainsTable initialDomains={initialDomains} />
    </div>
  );
}
