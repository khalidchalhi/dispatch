"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { formatTimestamp } from "@/lib/formatters";
import {
  capsForPreset,
  PRESET_TOTAL_DAYS,
} from "@/app/(dashboard)/domains/_lib/warmup-queries";
import type { WarmupPreset, WarmupStatus } from "@/types/domain";

const FIVE_X_MULTIPLIER = 5;

const presetLabels: Record<Exclude<WarmupPreset, "custom">, string> = {
  conservative: "Conservative (45 days)",
  standard: "Standard (30 days)",
  aggressive: "Aggressive (21 days)",
};

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Warmup progress"
      className="h-2 w-full overflow-hidden rounded-full bg-border"
    >
      <div
        className="h-full rounded-full bg-primary transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

type WarmupTabProps = {
  domainId: string;
  warmup: WarmupStatus;
};

export function WarmupTab({ domainId, warmup }: WarmupTabProps) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [selectedPreset, setSelectedPreset] = useState<WarmupPreset>(
    warmup.schedule.preset,
  );
  const [aggressiveConfirm, setAggressiveConfirm] = useState(false);
  const [extensionDays, setExtensionDays] = useState("7");
  const [saving, setSaving] = useState(false);
  const [extending, setExtending] = useState(false);

  const pctComplete =
    warmup.totalDays > 0
      ? Math.round((warmup.currentDay / warmup.totalDays) * 100)
      : 0;
  const isOverpacing = warmup.todaySends > warmup.todayCap;
  const utilizationPct =
    warmup.todayCap > 0
      ? Math.min(100, Math.round((warmup.todaySends / warmup.todayCap) * 100))
      : 0;

  function nextDayCapForPreset(preset: WarmupPreset): number {
    const caps = capsForPreset(preset);
    return caps[warmup.currentDay] ?? caps.at(-1) ?? warmup.todayCap;
  }

  function isUnsafePreset(preset: WarmupPreset): boolean {
    return nextDayCapForPreset(preset) > warmup.todayCap * FIVE_X_MULTIPLIER;
  }

  const unsafeSelected = isUnsafePreset(selectedPreset);
  const canSave = !unsafeSelected || aggressiveConfirm;

  async function handleSave() {
    setSaving(true);
    try {
      await clientJson(apiEndpoints.domains.warmup(domainId), {
        method: "PATCH",
        body: { preset: selectedPreset },
      });
      toast.success("Warmup schedule updated.");
      router.refresh();
      setEditing(false);
      setAggressiveConfirm(false);
    } catch {
      toast.error("Failed to save schedule. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function handleExtend() {
    const days = Number.parseInt(extensionDays, 10);
    if (!Number.isFinite(days) || days <= 0) {
      toast.error("Enter a positive number of extension days.");
      return;
    }

    setExtending(true);
    try {
      await clientJson(apiEndpoints.domains.warmupExtend(domainId), {
        method: "POST",
        body: { days },
      });
      toast.success(`Warmup extended by ${days} days.`);
      router.refresh();
    } catch {
      toast.error("Failed to extend warmup. Please try again.");
    } finally {
      setExtending(false);
    }
  }

  const remainingDays = warmup.schedule.days.slice(warmup.currentDay, warmup.currentDay + 7);
  const extensionDayCount = Number.parseInt(extensionDays, 10);
  const extensionLabel =
    Number.isFinite(extensionDayCount) && extensionDayCount > 0
      ? `Extend by ${extensionDayCount} ${extensionDayCount === 1 ? "day" : "days"}`
      : "Extend warmup";

  return (
    <div className="grid gap-6">
      {/* Progress header */}
      <div className="grid gap-3">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">
            {warmup.currentDay === 0
              ? "Not yet started"
              : `Day ${warmup.currentDay} of ${warmup.totalDays}`}
          </span>
          <span className="text-text-muted">{pctComplete}% complete</span>
        </div>
        <ProgressBar pct={pctComplete} />
        <div className="flex items-center gap-6 text-sm text-text-muted">
          <span>
            Today&apos;s cap:{" "}
            <span className="font-medium text-foreground">
              {warmup.todayCap.toLocaleString()}
            </span>
          </span>
          <span>
            Sends today:{" "}
            <span
              className={`font-medium ${isOverpacing ? "text-danger" : "text-foreground"}`}
            >
              {warmup.todaySends.toLocaleString()}
            </span>
          </span>
          <span>
            Utilization:{" "}
            <span className="font-medium text-foreground">{utilizationPct}%</span>
          </span>
        </div>
        {warmup.scheduledGraduationAt && !warmup.graduatedAt && (
          <p className="text-xs text-text-muted">
            Scheduled graduation:{" "}
            <span className="font-medium text-foreground">
              {formatTimestamp(warmup.scheduledGraduationAt)}
            </span>
          </p>
        )}
      </div>

      {/* Overpacing banner */}
      {isOverpacing && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-md border border-danger/30 bg-danger/5 p-4 text-sm"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
          <div>
            <p className="font-medium text-danger">Volume exceeding cap</p>
            <p className="text-foreground">
              Today&apos;s sends ({warmup.todaySends.toLocaleString()}) exceed the
              scheduled cap ({warmup.todayCap.toLocaleString()}). Review send queues
              and consider pausing campaigns on this domain.
            </p>
          </div>
        </div>
      )}

      {/* Graduation notice */}
      {warmup.graduatedAt && (
        <div className="flex items-start gap-3 rounded-md border border-success/30 bg-success/5 p-4 text-sm">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
          <div>
            <p className="font-medium text-success">Warmup complete</p>
            <p className="text-foreground">
              This domain graduated from warmup on{" "}
              {formatTimestamp(warmup.graduatedAt)}. Send limits are no longer
              restricted by the warmup schedule.
            </p>
          </div>
        </div>
      )}

      {/* Upcoming days table */}
      {remainingDays.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium">Upcoming schedule</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-muted">
                  <th className="pb-2 pr-6 font-medium">Day</th>
                  <th className="pb-2 pr-6 font-medium">Cap</th>
                  <th className="pb-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {remainingDays.map((d) => {
                  const isToday = d.day === warmup.currentDay + 1;
                  return (
                    <tr
                      key={d.day}
                      className={`border-b border-border/50 ${isToday ? "bg-primary/5" : ""}`}
                      aria-current={isToday ? "true" : undefined}
                    >
                      <td className="py-2 pr-6 tabular-nums">
                        {isToday ? (
                          <span className="font-semibold">Day {d.day} (today)</span>
                        ) : (
                          `Day ${d.day}`
                        )}
                      </td>
                      <td className="py-2 pr-6 tabular-nums font-medium">
                        {d.cap.toLocaleString()}
                      </td>
                      <td className="py-2">
                        <Badge variant={isToday ? "warning" : "muted"}>
                          {isToday ? "active" : "upcoming"}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Actions */}
      {!warmup.graduatedAt && (
        <div className="flex items-center gap-3 border-t border-border pt-4">
          {!editing && (
            <>
              <div className="flex items-center gap-2">
                <label htmlFor="extend-days" className="text-xs text-text-muted">
                  Days
                </label>
                <input
                  id="extend-days"
                  type="number"
                  min={1}
                  className="h-8 w-20 rounded-md border border-border bg-background px-2 text-sm"
                  value={extensionDays}
                  onChange={(event) => setExtensionDays(event.target.value)}
                />
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={extending}
                onClick={() => void handleExtend()}
              >
                <TrendingUp className="mr-2 h-3.5 w-3.5" aria-hidden />
                {extensionLabel}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setEditing(true)}
              >
                Edit schedule
              </Button>
            </>
          )}
        </div>
      )}

      {/* Schedule editor */}
      {editing && (
        <div className="grid gap-4 rounded-md border border-border p-4">
          <p className="text-sm font-medium">Choose a preset schedule</p>
          <div className="flex flex-wrap gap-2">
            {(["conservative", "standard", "aggressive"] as const).map(
              (preset) => (
                <button
                  key={preset}
                  type="button"
                  aria-pressed={selectedPreset === preset}
                  onClick={() => {
                    setSelectedPreset(preset);
                    setAggressiveConfirm(false);
                  }}
                  className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                    selectedPreset === preset
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:border-primary/50"
                  }`}
                >
                  {presetLabels[preset]}
                </button>
              ),
            )}
          </div>

          {/* Preview next day cap */}
          <p className="text-xs text-text-muted">
            Tomorrow&apos;s cap with this schedule:{" "}
            <span className="font-medium text-foreground">
              {nextDayCapForPreset(selectedPreset).toLocaleString()}
            </span>
            {" "}(over {PRESET_TOTAL_DAYS[selectedPreset as Exclude<WarmupPreset, "custom">] ?? warmup.totalDays} days total)
          </p>

          {/* 5× safety warning */}
          {unsafeSelected && (
            <div
              role="alert"
              className="rounded-md border border-warning/40 bg-warning/5 p-3 text-sm"
            >
              <p className="font-medium text-warning">Aggressive schedule warning</p>
              <p className="mt-1 text-foreground">
                Tomorrow&apos;s cap ({nextDayCapForPreset(selectedPreset).toLocaleString()}) is
                more than 5× today&apos;s cap ({warmup.todayCap.toLocaleString()}). This may
                damage inbox reputation. Confirm to proceed.
              </p>
              <label className="mt-3 flex cursor-pointer items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={aggressiveConfirm}
                  onChange={(e) => setAggressiveConfirm(e.target.checked)}
                  aria-label="I understand the risk of this aggressive schedule"
                />
                I understand the risk and want to proceed
              </label>
            </div>
          )}

          <div className="flex items-center gap-3">
            <Button
              size="sm"
              disabled={!canSave || saving}
              onClick={() => void handleSave()}
            >
              {saving ? "Saving…" : "Save schedule"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setEditing(false);
                setSelectedPreset(warmup.schedule.preset);
                setAggressiveConfirm(false);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
