import { CampaignWizard } from "./_components/campaign-wizard";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import type { SenderProfile } from "@/types/domain";
import { toSegment, type ApiSegmentsListResponse } from "@/app/(dashboard)/segments/_lib/segments-api";
import { toTemplate, toTemplateVersion, type ApiTemplateListResponse } from "@/app/(dashboard)/templates/_lib/templates-api";
import { toList, type ApiListCollectionResponse } from "@/app/(dashboard)/lists/_lib/lists-api";
import type { WizardTemplate } from "./_lib/wizard-types";

type DomainsListApiResponse = {
  items: Array<{
    id: string;
    name: string;
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

function toWizardTemplate(item: ApiTemplateListResponse["items"][number]): WizardTemplate {
  return {
    ...toTemplate(item),
    versions: item.versions.map(toTemplateVersion),
  };
}

export default async function CampaignCreatePage() {
  const [domainsResponse, senderProfilesResponse, templatesResponse, segmentsResponse, listsResponse] =
    await Promise.all([
      serverJson<DomainsListApiResponse>(ENDPOINTS.domains.list),
      serverJson<SenderProfilesListApiResponse>(ENDPOINTS.senderProfiles.list),
      serverJson<ApiTemplateListResponse>(ENDPOINTS.templates.list),
      serverJson<ApiSegmentsListResponse>(ENDPOINTS.segments.list),
      serverJson<ApiListCollectionResponse>(ENDPOINTS.lists.list),
    ]);

  const domainNameById = new Map(domainsResponse.items.map((domain) => [domain.id, domain.name]));
  const senderProfiles = senderProfilesResponse.items.map((item) =>
    toSenderProfile(item, domainNameById.get(item.domain_id) ?? "Unknown domain"),
  );
  const templates = templatesResponse.items.map(toWizardTemplate);
  const segments = segmentsResponse.items.map(toSegment);
  const lists = listsResponse.items.map(toList);

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Create campaign</h1>
          <p className="page-description">
            Build and launch a campaign in a few steps.
          </p>
        </div>
      </header>
      <CampaignWizard
        senderProfiles={senderProfiles}
        templates={templates}
        segments={segments}
        lists={lists}
      />
    </div>
  );
}
