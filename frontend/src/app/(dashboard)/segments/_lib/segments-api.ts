import type { Segment } from "@/types/segment";

export type ApiSegmentResponse = {
  id: string;
  name: string;
  description: string | null;
  dsl_json: Segment["dslJson"];
  last_computed_count: number | null;
  last_computed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ApiSegmentsListResponse = {
  items: ApiSegmentResponse[];
};

export type ApiSegmentEvaluateResponse = {
  total_count: number;
  sample: Array<{
    id: string;
    email: string;
    lifecycle_status: string;
  }>;
};

export function toSegment(api: ApiSegmentResponse): Segment {
  return {
    id: api.id,
    name: api.name,
    description: api.description,
    dslJson: api.dsl_json,
    lastComputedCount: api.last_computed_count,
    lastComputedAt: api.last_computed_at,
    isArchived: false,
    createdAt: api.created_at,
    updatedAt: api.updated_at,
  };
}

