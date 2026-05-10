import type { CampaignDetail, CampaignStatus } from "@/types/campaign";

export type CampaignByIdApiResponse = {
  id: string;
  name: string;
  status: string;
  updated_at: string;
};

function toCampaignStatus(
  value: string,
  fallback: CampaignStatus,
): CampaignStatus {
  if (value === "draft") return "draft";
  if (value === "scheduled") return "scheduled";
  if (value === "running") return "running";
  if (value === "paused") return "paused";
  if (value === "completed") return "completed";
  if (value === "cancelled") return "cancelled";
  if (value === "failed") return "failed";
  return fallback;
}

export function mergeCampaignDetailFromApi(
  current: CampaignDetail,
  payload: CampaignByIdApiResponse,
): CampaignDetail {
  return {
    ...current,
    id: payload.id || current.id,
    name: payload.name || current.name,
    status: toCampaignStatus(payload.status, current.status),
    updatedAt: payload.updated_at || current.updatedAt,
  };
}
