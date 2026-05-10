import { notFound } from "next/navigation";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import {
  campaigns,
  getMockCampaignDetail,
  getMockMessagesPage,
} from "../_lib/campaigns-queries";
import {
  mergeCampaignDetailFromApi,
  type CampaignByIdApiResponse,
} from "../_lib/campaigns-api";
import { getBreakerForEntity } from "@/app/(dashboard)/ops/_lib/ops-queries";
import { CampaignMonitor } from "./_components/campaign-monitor";

type CampaignDetailPageProps = {
  params: Promise<{ campaignId: string }>;
};

export default async function CampaignDetailPage({
  params,
}: CampaignDetailPageProps) {
  const { campaignId } = await params;

  const fallbackDetail = getMockCampaignDetail(campaignId);
  let detail = fallbackDetail;
  try {
    const liveCampaign = await serverJson<CampaignByIdApiResponse>(
      ENDPOINTS.campaigns.byId(campaignId),
    );
    detail = mergeCampaignDetailFromApi(fallbackDetail, liveCampaign);
  } catch {
    // Keep mock-backed fallback during incremental rewiring.
    const existsLocally = campaigns.some((campaign) => campaign.id === campaignId);
    if (!existsLocally) {
      notFound();
    }
  }

  const initialPage = getMockMessagesPage(campaignId, null, null);
  const domainBreaker = getBreakerForEntity("domain", detail.domainId);

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Campaign monitoring</h1>
        </div>
      </header>
      <CampaignMonitor
        initialDetail={detail}
        initialPage={initialPage}
        domainBreakerState={domainBreaker?.state ?? "closed"}
        domainId={detail.domainId}
      />
    </div>
  );
}
