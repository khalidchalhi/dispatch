import { PageIntro } from "@/components/patterns/page-intro";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import type { DomainListItem, DomainStatus, SenderProfile } from "@/types/domain";
import { SenderProfilesManager } from "./_components/sender-profiles-manager";

type DomainsListApiResponse = {
  items: Array<{
    id: string;
    name: string;
    verification_status: string;
    reputation_status: string;
    updated_at: string;
  }>;
};

type SenderProfilesListApiResponse = {
  items: Array<{
    id: string;
    display_name: string;
    from_name: string;
    from_email: string;
    reply_to: string | null;
    domain_id: string;
    ip_pool_id: string | null;
    is_active: boolean;
    created_at: string;
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

function toSenderProfile(
  item: SenderProfilesListApiResponse["items"][number],
  domainName: string,
): SenderProfile {
  return {
    id: item.id,
    name: item.display_name,
    fromName: item.from_name,
    fromEmail: item.from_email,
    replyTo: item.reply_to,
    domainId: item.domain_id,
    domainName,
    ipPool: item.ip_pool_id,
    status: item.is_active ? "active" : "suspended",
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  };
}

export default async function SenderProfilesPage() {
  const [domainsResponse, profilesResponse] = await Promise.all([
    serverJson<DomainsListApiResponse>(ENDPOINTS.domains.list),
    serverJson<SenderProfilesListApiResponse>(ENDPOINTS.senderProfiles.list),
  ]);

  const allDomains = domainsResponse.items.map(toDomainListItem);
  const verifiedDomains = allDomains.filter((domain) => domain.status === "verified");
  const domainNameById = new Map(allDomains.map((domain) => [domain.id, domain.name]));
  const senderProfiles = profilesResponse.items.map((item) =>
    toSenderProfile(item, domainNameById.get(item.domain_id) ?? "Unknown domain"),
  );

  return (
    <div className="page-stack">
      <PageIntro
        title="Sender profiles"
        description="Define the from addresses and display names used in outgoing campaigns. Only verified domains may be used."
      />
      <SenderProfilesManager
        initialProfiles={senderProfiles}
        verifiedDomains={verifiedDomains}
      />
    </div>
  );
}
