"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/shared/empty-state";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { formatTimestamp } from "@/lib/formatters";
import { newEmptyDsl } from "../_lib/segments-queries";
import { toSegment, type ApiSegmentsListResponse } from "../_lib/segments-api";
import type { Segment } from "@/types/segment";

type SegmentsManagerProps = {
  initialSegments: Segment[];
};

export function SegmentsManager({ initialSegments }: SegmentsManagerProps) {
  const router = useRouter();
  const [segments, setSegments] = useState<Segment[]>(initialSegments);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<Segment | null>(null);

  const active = segments.filter((s) => !s.isArchived);

  async function refreshSegments() {
    const response = await clientJson<ApiSegmentsListResponse>(apiEndpoints.segments.list);
    setSegments(response.items.map(toSegment));
  }

  async function handleCreate() {
    if (!newName.trim()) return;
    setIsCreating(true);
    try {
      const segment = await clientJson<Segment>(apiEndpoints.segments.create, {
        method: "POST",
        body: {
          name: newName.trim(),
          description: newDescription.trim() || null,
          dsl_json: newEmptyDsl(),
        },
      });
      toast.success("Segment created.");
      setCreateOpen(false);
      setNewName("");
      setNewDescription("");
      router.push(`/segments/${segment.id}`);
      router.refresh();
    } catch {
      toast.error("Failed to create segment.");
    } finally {
      setIsCreating(false);
    }
  }

  async function handleDuplicate(segment: Segment) {
    try {
      await clientJson<Segment>(
        apiEndpoints.segments.duplicate(segment.id),
        { method: "POST" },
      );
      await refreshSegments();
      toast.success(`"${segment.name}" duplicated.`);
    } catch {
      toast.error("Failed to duplicate segment.");
    }
  }

  async function handleArchive(segment: Segment) {
    try {
      await clientJson(apiEndpoints.segments.delete(segment.id), {
        method: "DELETE",
      });
      setSegments((prev) =>
        prev.map((s) => (s.id === segment.id ? { ...s, isArchived: true } : s)),
      );
      toast.success(`"${segment.name}" archived.`);
    } catch {
      toast.error("Failed to archive segment.");
    } finally {
      setArchiveTarget(null);
    }
  }

  return (
    <>
      <div className="flex justify-end">
        <Button type="button" onClick={() => setCreateOpen(true)}>
          New segment
        </Button>
      </div>

      {active.length === 0 ? (
        <EmptyState
          title="No segments yet"
          description="Build your first query-based audience."
          action={
            <Button type="button" onClick={() => setCreateOpen(true)}>
              New segment
            </Button>
          }
        />
      ) : (
        <div className="surface-panel overflow-hidden">
          <table className="w-full text-sm" aria-label="Segment list">
            <thead>
              <tr className="border-b border-border">
                <th className="px-4 py-3 text-left font-medium text-text-muted">
                  Name
                </th>
                <th className="px-4 py-3 text-left font-medium text-text-muted">
                  Last count
                </th>
                <th className="px-4 py-3 text-left font-medium text-text-muted">
                  Last computed
                </th>
                <th className="px-4 py-3 text-right font-medium text-text-muted">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {active.map((segment) => (
                <tr
                  key={segment.id}
                  className="border-b border-border last:border-0 hover:bg-surface-muted/50 transition-colors"
                >
                  <td className="px-4 py-3">
                    <Link
                      href={`/segments/${segment.id}`}
                      className="font-medium hover:underline underline-offset-2"
                    >
                      {segment.name}
                    </Link>
                    {segment.description ? (
                      <p className="text-xs text-text-muted mt-0.5">
                        {segment.description}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    {segment.lastComputedCount != null ? (
                      <Badge variant="muted">
                        {segment.lastComputedCount.toLocaleString()}
                      </Badge>
                    ) : (
                      <span className="text-xs text-text-muted">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-text-muted">
                    {segment.lastComputedAt
                      ? formatTimestamp(segment.lastComputedAt)
                      : "Never"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void handleDuplicate(segment)}
                      >
                        Duplicate
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setArchiveTarget(segment)}
                      >
                        Archive
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create segment</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="label" htmlFor="new-segment-name">
                Name
              </label>
              <Input
                id="new-segment-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g. Active newsletter subscribers"
                autoFocus
              />
            </div>
            <div>
              <label className="label" htmlFor="new-segment-description">
                Description{" "}
                <span className="font-normal text-text-muted">(optional)</span>
              </label>
              <Input
                id="new-segment-description"
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                placeholder="Who does this segment target?"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setCreateOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!newName.trim() || isCreating}
              onClick={() => void handleCreate()}
            >
              {isCreating ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Archive confirm */}
      <Dialog open={archiveTarget !== null} onOpenChange={(open) => { if (!open) setArchiveTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Archive segment</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-text-muted">
            &quot;{archiveTarget?.name}&quot; will be archived and removed from this list.
            Active campaign runs using it will not be affected.
          </p>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setArchiveTarget(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => archiveTarget && void handleArchive(archiveTarget)}
            >
              Archive
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
