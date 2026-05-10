"use client";

import { Button } from "@/components/ui/button";
import type { CampaignDraft } from "@/types/campaign";
import type { WizardTemplate } from "../_lib/wizard-types";

type StepTemplateProps = {
  draft: CampaignDraft;
  templates: WizardTemplate[];
  onChange: (patch: Partial<CampaignDraft>) => void;
  onBack: () => void;
  onNext: () => void;
};

export function StepTemplate({
  draft,
  templates,
  onChange,
  onBack,
  onNext,
}: StepTemplateProps) {
  const selectedTemplate = templates.find((t) => t.id === draft.templateId);
  const versions = selectedTemplate?.versions ?? [];
  const selectedVersion = versions.find((v) => v.version === draft.templateVersion);

  function handleTemplateChange(id: string) {
    const tmpl = templates.find((t) => t.id === id);
    const vers = tmpl?.versions ?? [];
    const defaultVersion = vers.find((v) => v.version === tmpl?.activeVersion) ?? vers.at(-1);
    onChange({
      templateId: id,
      templateVersion: defaultVersion?.version ?? null,
    });
  }

  const canContinue = draft.templateId !== "" && draft.templateVersion !== null;

  return (
    <div className="grid gap-6">
      <div className="surface-panel p-6 grid gap-5">
        <div>
          <label className="label" htmlFor="template-select">
            Template
          </label>
          <select
            id="template-select"
            className="field h-9 w-full max-w-sm"
            value={draft.templateId}
            onChange={(e) => handleTemplateChange(e.target.value)}
          >
            <option value="">Select a template…</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>

        {draft.templateId ? (
          <div>
            <label className="label" htmlFor="version-select">
              Version
            </label>
            <select
              id="version-select"
              className="field h-9 w-full max-w-sm"
              value={draft.templateVersion ?? ""}
              onChange={(e) =>
                onChange({ templateVersion: Number(e.target.value) || null })
              }
            >
              <option value="">Select a version…</option>
              {versions.map((v) => (
                <option key={v.id} value={v.version}>
                  v{v.version}
                  {v.version === selectedTemplate?.activeVersion ? " (active)" : ""}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {selectedVersion ? (
          <div className="surface-panel-muted rounded-lg p-4">
            <p className="text-xs font-medium text-text-muted uppercase tracking-wide mb-1">
              Subject preview
            </p>
            <p className="text-sm font-medium">{selectedVersion.subject}</p>
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
