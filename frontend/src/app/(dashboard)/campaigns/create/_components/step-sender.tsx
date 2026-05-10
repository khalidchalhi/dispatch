"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { CampaignDraft } from "@/types/campaign";
import type { SenderProfile } from "@/types/domain";

type StepSenderProps = {
  draft: CampaignDraft;
  senderProfiles: SenderProfile[];
  onChange: (patch: Partial<CampaignDraft>) => void;
  onBack: () => void;
  onNext: () => void;
};

export function StepSender({
  draft,
  senderProfiles,
  onChange,
  onBack,
  onNext,
}: StepSenderProps) {
  const activeSenders = senderProfiles.filter((sp) => sp.status === "active");

  return (
    <div className="grid gap-6">
      <div className="surface-panel p-6 grid gap-4">
        <p className="text-sm text-text-muted">
          Select the sender profile to use for this campaign. Only profiles on
          verified domains are shown.
        </p>

        <fieldset>
          <legend className="label mb-3">Sender profile</legend>
          <div className="grid gap-3">
            {activeSenders.map((sp) => {
              const selected = draft.senderProfileId === sp.id;
              return (
                <label
                  key={sp.id}
                  className={`flex cursor-pointer items-start gap-4 rounded-lg border p-4 transition-colors ${
                    selected
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/40"
                  }`}
                >
                  <input
                    type="radio"
                    name="sender-profile"
                    value={sp.id}
                    checked={selected}
                    onChange={() => onChange({ senderProfileId: sp.id })}
                    className="mt-0.5"
                    aria-label={`Select sender: ${sp.name}`}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm">{sp.name}</span>
                      <Badge variant="success">Active</Badge>
                    </div>
                    <p className="mono text-xs text-text-muted mt-0.5">
                      {sp.fromName} &lt;{sp.fromEmail}&gt;
                    </p>
                    <p className="text-xs text-text-muted mt-0.5">
                      Domain: {sp.domainName} · Pool: {sp.ipPool}
                    </p>
                  </div>
                </label>
              );
            })}
          </div>
        </fieldset>
      </div>

      <div className="flex justify-between gap-3">
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button
          type="button"
          disabled={!draft.senderProfileId}
          onClick={onNext}
        >
          Continue
        </Button>
      </div>
    </div>
  );
}
