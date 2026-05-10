import Link from "next/link";
import { notFound } from "next/navigation";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/errors";
import { SegmentWorkspace } from "../_components/segment-workspace";
import { toSegment, type ApiSegmentResponse } from "../_lib/segments-api";

type SegmentDetailPageProps = {
  params: Promise<{ segmentId: string }>;
};

export default async function SegmentDetailPage({
  params,
}: SegmentDetailPageProps) {
  const { segmentId } = await params;
  let segmentResponse: ApiSegmentResponse;
  try {
    segmentResponse = await serverJson<ApiSegmentResponse>(
      ENDPOINTS.segments.byId(segmentId),
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  const segment = toSegment(segmentResponse);

  return (
    <div className="page-stack">
      <nav
        className="flex items-center gap-2 text-sm text-text-muted"
        aria-label="Breadcrumb"
      >
        <Link href="/segments" className="hover:underline">
          Segments
        </Link>
        <span aria-hidden="true">/</span>
        <span>{segment.name}</span>
      </nav>

      <header className="page-intro">
        <div className="page-intro-copy">
          <h1 className="page-title">{segment.name}</h1>
          {segment.description ? (
            <p className="page-description">{segment.description}</p>
          ) : null}
        </div>
      </header>

      <SegmentWorkspace segment={segment} />
    </div>
  );
}
