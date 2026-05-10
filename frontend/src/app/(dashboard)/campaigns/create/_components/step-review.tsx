"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import type {
  CampaignDraft,
  PreflightCheck,
  PreflightSeverity,
} from "@/types/campaign";
import type { SenderProfile } from "@/types/domain";
import type { List } from "@/types/list";
import type { Segment } from "@/types/segment";
import type { WizardTemplate } from "../_lib/wizard-types";

type CampaignMutationResponse = {
  id: string;
};

type CampaignPreflightApiResponse = {
  campaign_id: string;
  checks: Array<{
    id: string;
    label: string;
    severity: string;
    detail: string;
  }>;
  has_critical: boolean;
  generated_at: string;
};

const severityVariant: Record<PreflightSeverity, "success" | "warning" | "danger"> = {
  ok: "success",
  warning: "warning",
  critical: "danger",
};

const severityLabel: Record<PreflightSeverity, string> = {
  ok: "OK",
  warning: "Warning",
  critical: "Critical",
};

function toSeverity(value: string): PreflightSeverity {
  if (value === "ok") return "ok";
  if (value === "warning") return "warning";
  if (value === "critical") return "critical";
  return "warning";
}

function toPreflightCheck(item: CampaignPreflightApiResponse["checks"][number]): PreflightCheck {
  return {
    id: item.id,
    label: item.label,
    severity: toSeverity(item.severity),
    detail: item.detail,
  };
}

function resolveScheduledAt(draft: CampaignDraft): string | null {
  if (draft.scheduleType !== "scheduled") return null;
  const value = draft.scheduledAt.trim();
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

function buildCampaignPayload(draft: CampaignDraft) {
  return {
    name: draft.name.trim(),
    campaignType: "outreach",
    senderProfileId: draft.senderProfileId,
    templateId: draft.templateId,
    templateVersion: draft.templateVersion,
    audienceType: draft.audienceType,
    audienceId: draft.audienceId,
    scheduleType: draft.scheduleType,
    scheduledAt: resolveScheduledAt(draft),
    timezone: draft.timezone,
    sendRatePerHour: 100,
    trackingOpens: false,
    trackingClicks: false,
  };
}

type StepReviewProps = {
  draft: CampaignDraft;
  senderProfiles: SenderProfile[];
  templates: WizardTemplate[];
  segments: Segment[];
  lists: List[];
  onChange: (patch: Partial<CampaignDraft>) => void;
  onBack: () => void;
  onGoToStep: (step: number) => void;
  onLaunchSuccess: () => void;
};

export function StepReview({
  draft,
  senderProfiles,
  templates,
  segments,
  lists,
  onChange,
  onBack,
  onGoToStep,
  onLaunchSuccess,
}: StepReviewProps) {
  const router = useRouter();
  const [launchOpen, setLaunchOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [isLaunching, setIsLaunching] = useState(false);
  const [isPreparing, setIsPreparing] = useState(false);
  const [isRunningPreflight, setIsRunningPreflight] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [preflightChecks, setPreflightChecks] = useState<PreflightCheck[]>([]);

  const sender = senderProfiles.find((sp) => sp.id === draft.senderProfileId);
  const template = templates.find((t) => t.id === draft.templateId);
  const templateVersion = template?.versions.find(
    (v) => v.version === draft.templateVersion,
  );

  const audience =
    draft.audienceType === "segment"
      ? segments.find((s) => s.id === draft.audienceId)
      : lists.find((l) => l.id === draft.audienceId);

  const audienceCount =
    draft.audienceType === "segment"
      ? (segments.find((s) => s.id === draft.audienceId)?.lastComputedCount ?? 0)
      : (lists.find((l) => l.id === draft.audienceId)?.memberCount ?? 0);

  const canPrepareCampaign = useMemo(() => {
    if (!draft.name.trim()) return false;
    if (!draft.senderProfileId || !draft.templateId || draft.templateVersion === null) return false;
    if (!draft.audienceId) return false;
    if (draft.scheduleType === "scheduled" && !resolveScheduledAt(draft)) return false;
    return true;
  }, [draft]);

  const preflightKey = useMemo(
    () =>
      JSON.stringify({
        name: draft.name.trim(),
        senderProfileId: draft.senderProfileId,
        templateId: draft.templateId,
        templateVersion: draft.templateVersion,
        audienceType: draft.audienceType,
        audienceId: draft.audienceId,
        scheduleType: draft.scheduleType,
        scheduledAt: resolveScheduledAt(draft),
        timezone: draft.timezone,
      }),
    [draft],
  );

  async function upsertCampaign(): Promise<string> {
    const payload = buildCampaignPayload(draft);
    if (draft.campaignId) {
      const updated = await clientJson<CampaignMutationResponse>(
        apiEndpoints.campaigns.update(draft.campaignId),
        {
          method: "PATCH",
          body: payload,
        },
      );
      return updated.id;
    }

    const created = await clientJson<CampaignMutationResponse>(apiEndpoints.campaigns.create, {
      method: "POST",
      body: payload,
    });
    onChange({ campaignId: created.id });
    return created.id;
  }

  async function runPreflight() {
    if (!canPrepareCampaign) return;
    setIsPreparing(true);
    setPreflightError(null);
    try {
      const campaignId = await upsertCampaign();
      setIsRunningPreflight(true);
      const response = await clientJson<CampaignPreflightApiResponse>(
        apiEndpoints.campaigns.preflight(campaignId),
        { method: "POST" },
      );
      setPreflightChecks(response.checks.map(toPreflightCheck));
    } catch {
      setPreflightChecks([]);
      setPreflightError("Could not run pre-launch checks. Review your inputs and retry.");
    } finally {
      setIsPreparing(false);
      setIsRunningPreflight(false);
    }
  }

  useEffect(() => {
    let isCancelled = false;
    async function run() {
      if (isCancelled || !canPrepareCampaign) return;
      await runPreflight();
    }
    void run();
    return () => {
      isCancelled = true;
    };
  }, [preflightKey, canPrepareCampaign]);

  const hasCritical = preflightChecks.some((check) => check.severity === "critical");
  const canLaunch =
    canPrepareCampaign &&
    preflightChecks.length > 0 &&
    !hasCritical &&
    !isPreparing &&
    !isRunningPreflight &&
    !isLaunching;

  async function handleLaunch() {
    if (confirmName !== draft.name || isLaunching) return;
    setIsLaunching(true);
    try {
      const campaignId = await upsertCampaign();
      await clientJson(apiEndpoints.campaigns.launch(campaignId), { method: "POST" });
      onLaunchSuccess();
      toast.success(`"${draft.name}" launched successfully.`);
      router.push(`/campaigns/${campaignId}`);
    } catch {
      toast.error("Launch failed. Please retry or contact support.");
    } finally {
      setIsLaunching(false);
      setLaunchOpen(false);
    }
  }

  return (
    <div className="grid gap-6">
      <div className="surface-panel p-6 grid gap-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="section-title">Review</h2>
        </div>

        <dl className="summary-list">
          <div className="summary-row">
            <dt className="text-sm font-medium">Name</dt>
            <dd className="flex items-center gap-2">
              <span className="text-sm">{draft.name}</span>
              <button
                type="button"
                className="text-xs text-primary underline underline-offset-2"
                onClick={() => onGoToStep(0)}
              >
                Edit
              </button>
            </dd>
          </div>
          {draft.tag ? (
            <div className="summary-row">
              <dt className="text-sm font-medium">Tag</dt>
              <dd className="mono text-xs text-text-muted">{draft.tag}</dd>
            </div>
          ) : null}
          <div className="summary-row">
            <dt className="text-sm font-medium">Sender</dt>
            <dd className="flex items-center gap-2">
              <span className="text-sm">
                {sender ? `${sender.fromName} <${sender.fromEmail}>` : "—"}
              </span>
              <button
                type="button"
                className="text-xs text-primary underline underline-offset-2"
                onClick={() => onGoToStep(1)}
              >
                Edit
              </button>
            </dd>
          </div>
          <div className="summary-row">
            <dt className="text-sm font-medium">Template</dt>
            <dd className="flex items-center gap-2">
              <span className="text-sm">
                {template ? `${template.name} — v${draft.templateVersion}` : "—"}
              </span>
              <button
                type="button"
                className="text-xs text-primary underline underline-offset-2"
                onClick={() => onGoToStep(2)}
              >
                Edit
              </button>
            </dd>
          </div>
          {templateVersion ? (
            <div className="summary-row">
              <dt className="text-sm font-medium">Subject</dt>
              <dd className="text-sm text-text-muted italic">{templateVersion.subject}</dd>
            </div>
          ) : null}
          <div className="summary-row">
            <dt className="text-sm font-medium">Audience</dt>
            <dd className="flex items-center gap-2">
              <span className="text-sm">
                {audience ? audience.name : "—"}
                {audienceCount > 0 ? ` (${audienceCount.toLocaleString()})` : ""}
              </span>
              <button
                type="button"
                className="text-xs text-primary underline underline-offset-2"
                onClick={() => onGoToStep(3)}
              >
                Edit
              </button>
            </dd>
          </div>
          <div className="summary-row">
            <dt className="text-sm font-medium">Schedule</dt>
            <dd className="flex items-center gap-2">
              <span className="text-sm">
                {draft.scheduleType === "immediate"
                  ? "Send immediately"
                  : `${draft.scheduledAt} (${draft.timezone})`}
              </span>
              <button
                type="button"
                className="text-xs text-primary underline underline-offset-2"
                onClick={() => onGoToStep(4)}
              >
                Edit
              </button>
            </dd>
          </div>
        </dl>
      </div>

      <div className="surface-panel p-6 grid gap-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="section-title">Pre-launch checks</h2>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isPreparing || isRunningPreflight || !canPrepareCampaign}
            onClick={() => void runPreflight()}
          >
            {isRunningPreflight || isPreparing ? "Running…" : "Re-run checks"}
          </Button>
        </div>

        {preflightError ? (
          <p role="alert" className="text-sm text-danger">
            {preflightError}
          </p>
        ) : null}

        {preflightChecks.length > 0 ? (
          <ul role="list" className="grid gap-3">
            {preflightChecks.map((check) => (
              <li key={check.id} className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{check.label}</p>
                  <p className="text-xs text-text-muted mt-0.5">{check.detail}</p>
                </div>
                <Badge variant={severityVariant[check.severity]}>
                  {severityLabel[check.severity]}
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-text-muted">
            {isRunningPreflight || isPreparing
              ? "Running pre-launch checks…"
              : "No pre-launch checks yet."}
          </p>
        )}

        {hasCritical ? (
          <p role="alert" className="text-sm text-danger">
            One or more pre-launch checks are critical. Resolve them before launching.
          </p>
        ) : null}
      </div>

      <div className="flex justify-between gap-3">
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button
          type="button"
          disabled={!canLaunch}
          onClick={() => {
            setConfirmName("");
            setLaunchOpen(true);
          }}
        >
          Launch campaign
        </Button>
      </div>

      <Dialog
        open={launchOpen}
        onOpenChange={(open) => {
          if (!open) {
            setLaunchOpen(false);
            setConfirmName("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm launch</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <p className="text-sm text-text-muted">
              This will immediately queue{" "}
              <strong>{audienceCount.toLocaleString()}</strong> sends (after
              suppression exclusions). This action cannot be undone without pausing.
            </p>
            <div>
              <label className="label" htmlFor="confirm-campaign-name">
                Type the campaign name to confirm
              </label>
              <Input
                id="confirm-campaign-name"
                value={confirmName}
                onChange={(e) => setConfirmName(e.target.value)}
                placeholder={draft.name}
                autoFocus
              />
              <p className="mt-1 text-xs text-text-muted">
                Type: <span className="font-medium">{draft.name}</span>
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setLaunchOpen(false);
                setConfirmName("");
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={confirmName !== draft.name || isLaunching}
              onClick={() => void handleLaunch()}
            >
              {isLaunching ? "Launching…" : "Confirm launch"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
