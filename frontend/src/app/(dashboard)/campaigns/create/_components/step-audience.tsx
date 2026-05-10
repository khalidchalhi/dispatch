"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { CampaignDraft } from "@/types/campaign";
import type { List } from "@/types/list";
import type { Segment } from "@/types/segment";

type StepAudienceProps = {
  draft: CampaignDraft;
  segments: Segment[];
  lists: List[];
  onChange: (patch: Partial<CampaignDraft>) => void;
  onBack: () => void;
  onNext: () => void;
};

export function StepAudience({
  draft,
  segments,
  lists,
  onChange,
  onBack,
  onNext,
}: StepAudienceProps) {
  const activeSegments = segments.filter((s) => !s.isArchived);

  const selectedSegment =
    draft.audienceType === "segment"
      ? activeSegments.find((s) => s.id === draft.audienceId)
      : null;
  const selectedList =
    draft.audienceType === "list"
      ? lists.find((l) => l.id === draft.audienceId)
      : null;
  const audienceCount =
    selectedSegment?.lastComputedCount ??
    selectedList?.memberCount ??
    null;

  const canContinue = draft.audienceId !== "";

  return (
    <div className="grid gap-6">
      <div className="surface-panel p-6 grid gap-5">
        <div>
          <p className="label mb-3">Audience type</p>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="audience-type"
                value="segment"
                checked={draft.audienceType === "segment"}
                onChange={() => onChange({ audienceType: "segment", audienceId: "" })}
              />
              <span className="text-sm">Segment</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="audience-type"
                value="list"
                checked={draft.audienceType === "list"}
                onChange={() => onChange({ audienceType: "list", audienceId: "" })}
              />
              <span className="text-sm">List</span>
            </label>
          </div>
        </div>

        {draft.audienceType === "segment" ? (
          <div>
            <label className="label" htmlFor="audience-segment">
              Segment
            </label>
            <select
              id="audience-segment"
              className="field h-9 w-full max-w-sm"
              value={draft.audienceId}
              onChange={(e) => onChange({ audienceId: e.target.value })}
            >
              <option value="">Select a segment…</option>
              {activeSegments.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div>
            <label className="label" htmlFor="audience-list">
              List
            </label>
            <select
              id="audience-list"
              className="field h-9 w-full max-w-sm"
              value={draft.audienceId}
              onChange={(e) => onChange({ audienceId: e.target.value })}
            >
              <option value="">Select a list…</option>
              {lists.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {audienceCount !== null ? (
          <div className="surface-panel-muted rounded-lg p-4 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">Estimated audience size</p>
              <p className="text-xs text-text-muted mt-0.5">
                Before suppression exclusions are applied
              </p>
            </div>
            <Badge variant="muted">
              {audienceCount.toLocaleString()} contacts
            </Badge>
          </div>
        ) : null}
      </div>

      <div className="flex justify-between gap-3">
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button type="button" disabled={!canContinue} onClick={onNext}>
          Continue
        </Button>
      </div>
    </div>
  );
}
