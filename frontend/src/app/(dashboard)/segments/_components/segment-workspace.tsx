"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { ConditionGroup } from "./condition-group";
import { PreviewPanel } from "./preview-panel";
import { type Segment, type SegmentDsl, validateDsl } from "@/types/segment";

type SegmentWorkspaceProps = {
  segment: Segment;
};

export function SegmentWorkspace({ segment: initial }: SegmentWorkspaceProps) {
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description ?? "");
  const [dsl, setDsl] = useState<SegmentDsl>(initial.dslJson);
  const [isSaving, setIsSaving] = useState(false);
  const [hasUnsaved, setHasUnsaved] = useState(false);

  const validationError = validateDsl(dsl);
  const isValid = validationError === null;

  function handleDslChange(updated: SegmentDsl) {
    setDsl(updated);
    setHasUnsaved(true);
  }

  function handleNameChange(value: string) {
    setName(value);
    setHasUnsaved(true);
  }

  async function handleSave() {
    if (!isValid) return;
    setIsSaving(true);
    try {
      await clientJson<Segment>(apiEndpoints.segments.update(initial.id), {
        method: "PATCH",
        body: {
          name: name.trim(),
          description: description.trim() || null,
          dsl_json: dsl,
        },
      });
      setHasUnsaved(false);
      toast.success("Segment saved.");
    } catch {
      toast.error("Failed to save segment.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="grid gap-6">
      {/* Name + description */}
      <div className="surface-panel p-6 grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="segment-name">
              Segment name
            </label>
            <Input
              id="segment-name"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="e.g. Active newsletter subscribers"
            />
          </div>
          <div>
            <label className="label" htmlFor="segment-description">
              Description{" "}
              <span className="font-normal text-text-muted">(optional)</span>
            </label>
            <Input
              id="segment-description"
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
                setHasUnsaved(true);
              }}
              placeholder="Who does this segment target?"
            />
          </div>
        </div>
      </div>

      {/* Builder + preview */}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,0.7fr)]">
        <div className="grid gap-4">
          <div className="surface-panel p-6 grid gap-4">
            <h2 className="section-title">Conditions</h2>
            <ConditionGroup
              group={dsl}
              onChange={handleDslChange}
              depth={0}
            />
          </div>

          {validationError ? (
            <p role="alert" className="text-sm text-danger">
              {validationError}
            </p>
          ) : null}

          <div className="flex items-center justify-between gap-3">
            {hasUnsaved ? (
              <span className="text-xs text-text-muted" role="status" aria-live="polite">
                Unsaved changes
              </span>
            ) : (
              <span />
            )}
            <Button
              type="button"
              disabled={!hasUnsaved || !isValid || isSaving || !name.trim()}
              onClick={() => void handleSave()}
            >
              {isSaving ? "Saving…" : "Save segment"}
            </Button>
          </div>
        </div>

        <PreviewPanel
          segmentId={initial.id}
          dsl={dsl}
          isValid={isValid}
        />
      </div>
    </div>
  );
}
