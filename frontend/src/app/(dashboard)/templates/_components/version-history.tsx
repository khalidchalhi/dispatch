"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatTimestamp } from "@/lib/formatters";
import type { TemplateVersion } from "@/types/template";

type DiffLine =
  | { type: "unchanged"; text: string }
  | { type: "removed"; text: string }
  | { type: "added"; text: string };

function computeDiff(a: string, b: string): DiffLine[] {
  const linesA = a.split("\n");
  const linesB = b.split("\n");

  // Simple LCS-based diff
  const dp: number[][] = Array.from({ length: linesA.length + 1 }, () =>
    new Array<number>(linesB.length + 1).fill(0),
  );
  for (let i = linesA.length - 1; i >= 0; i--) {
    for (let j = linesB.length - 1; j >= 0; j--) {
      if (linesA[i] === linesB[j]) {
        dp[i]![j] = 1 + dp[i + 1]![j + 1]!;
      } else {
        dp[i]![j] = Math.max(dp[i + 1]![j]!, dp[i]![j + 1]!);
      }
    }
  }

  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < linesA.length || j < linesB.length) {
    if (i < linesA.length && j < linesB.length && linesA[i] === linesB[j]) {
      result.push({ type: "unchanged", text: linesA[i]! });
      i++;
      j++;
    } else if (
      j < linesB.length &&
      (i >= linesA.length || dp[i]![j + 1]! >= dp[i + 1]![j]!)
    ) {
      result.push({ type: "added", text: linesB[j]! });
      j++;
    } else {
      result.push({ type: "removed", text: linesA[i]! });
      i++;
    }
  }
  return result;
}

type VersionHistoryProps = {
  versions: TemplateVersion[];
  activeVersion: number | null;
  onPublish?: (version: TemplateVersion) => void;
  publishingVersionId?: string | null;
  onRestore?: (version: TemplateVersion) => void;
  onSelect: (version: TemplateVersion) => void;
  selectedVersion: TemplateVersion | null;
};

export function VersionHistory({
  versions,
  activeVersion,
  onPublish,
  publishingVersionId = null,
  onRestore,
  onSelect,
  selectedVersion,
}: VersionHistoryProps) {
  const [diffBase, setDiffBase] = useState<TemplateVersion | null>(null);

  const sorted = [...versions].sort((a, b) => b.version - a.version);
  const actionLabel = onRestore ? "Restore" : "Publish";
  const pendingActionLabel = onRestore ? "Restoring…" : "Publishing…";
  const handleVersionAction = onRestore ?? onPublish;

  return (
    <div className="grid gap-4">
      <div className="surface-panel overflow-hidden">
        <div className="panel-header border-b border-border px-4 py-3">
          <h2 className="panel-title text-sm">Version history</h2>
        </div>
        <ul role="list" className="divide-y divide-border">
          {sorted.map((v) => (
            <li key={v.id} className="flex items-center gap-3 px-4 py-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">v{v.version}</span>
                  {v.version === activeVersion ? (
                    <Badge variant="success">Active</Badge>
                  ) : null}
                  {v.publishedAt ? null : (
                    <Badge variant="muted">Draft</Badge>
                  )}
                </div>
                <p className="text-xs text-text-muted mt-0.5">
                  {formatTimestamp(v.createdAt)}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onSelect(v)}
                  aria-pressed={selectedVersion?.id === v.id}
                >
                  View
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setDiffBase((prev) => (prev?.id === v.id ? null : v))}
                  aria-pressed={diffBase?.id === v.id}
                >
                  Diff
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => handleVersionAction?.(v)}
                  disabled={
                    !handleVersionAction ||
                    publishingVersionId === v.id ||
                    (!onRestore && v.version === activeVersion)
                  }
                >
                  {publishingVersionId === v.id ? pendingActionLabel : actionLabel}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </div>

      {diffBase && selectedVersion && diffBase.id !== selectedVersion.id ? (
        <DiffView a={diffBase} b={selectedVersion} />
      ) : null}
    </div>
  );
}

function DiffView({
  a,
  b,
}: {
  a: TemplateVersion;
  b: TemplateVersion;
}) {
  const subjectDiff = computeDiff(a.subject, b.subject);
  const bodyDiff = computeDiff(a.bodyText, b.bodyText);

  return (
    <div className="surface-panel overflow-hidden" aria-label="Version diff">
      <div className="panel-header border-b border-border px-4 py-3">
        <h3 className="panel-title text-sm">
          Diff v{a.version} → v{b.version}
        </h3>
      </div>
      <div className="p-4 grid gap-4">
        <section>
          <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
            Subject
          </h4>
          <DiffBlock lines={subjectDiff} />
        </section>
        <section>
          <h4 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
            Body (plain text)
          </h4>
          <DiffBlock lines={bodyDiff} />
        </section>
      </div>
    </div>
  );
}

function DiffBlock({ lines }: { lines: DiffLine[] }) {
  return (
    <pre className="mono text-xs overflow-x-auto rounded-lg bg-surface-muted p-3 leading-5">
      {lines.map((line, i) => (
        <div
          key={i}
          className={
            line.type === "added"
              ? "bg-green-500/10 text-green-700 dark:text-green-400"
              : line.type === "removed"
                ? "bg-red-500/10 text-red-700 dark:text-red-400 line-through"
                : ""
          }
        >
          {line.type === "added" ? "+ " : line.type === "removed" ? "- " : "  "}
          {line.text || " "}
        </div>
      ))}
    </pre>
  );
}
