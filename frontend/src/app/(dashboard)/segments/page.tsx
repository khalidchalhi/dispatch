import { SegmentsManager } from "./_components/segments-manager";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { toSegment, type ApiSegmentsListResponse } from "./_lib/segments-api";

export default async function SegmentsPage() {
  const response = await serverJson<ApiSegmentsListResponse>(ENDPOINTS.segments.list);
  const segments = response.items.map(toSegment);

  return (
    <div className="page-stack">
      <header className="page-intro">
        <div className="page-intro-copy">
          <h1 className="page-title">Segments</h1>
          <p className="page-description">
            Build query-based audiences with a visual predicate builder. Segments
            are evaluated at campaign launch and frozen into immutable snapshots.
          </p>
        </div>
      </header>

      <SegmentsManager initialSegments={segments} />
    </div>
  );
}
