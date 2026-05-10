"use client";

import { useState, useMemo } from "react";
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
import { publicEnv } from "@/lib/env";
import { formatTimestamp, maskEmailAddress } from "@/lib/formatters";
import type {
  SuppressionEntry,
  SuppressionReason,
  SuppressionSource,
  SuppressionSyncStatus,
} from "@/types/suppression";
import {
  SUPPRESSION_REASON_LABELS,
  SUPPRESSION_SOURCE_LABELS,
  SUPPRESSION_REASON_VARIANTS,
} from "@/types/suppression";
import type { ApiSuppressionRevealResponse } from "../_lib/suppression-api";

const PAGE_SIZE = 20;

const ALL_REASONS: SuppressionReason[] = [
  "hard_bounce",
  "spam_complaint",
  "soft_bounce",
  "unsubscribe",
  "manual",
];

const ALL_SOURCES: SuppressionSource[] = [
  "ses_event",
  "one_click",
  "csv_import",
  "api",
  "manual",
];

function parseEmailList(raw: string): string[] {
  const emails = raw
    .split(/[\n,]+/)
    .map((e) => e.trim().toLowerCase())
    .filter((e) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e));
  return [...new Set(emails)];
}

function downloadCsvBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}

type SuppressionManagerProps = {
  initialEntries: SuppressionEntry[];
  syncStatus: SuppressionSyncStatus;
  isAdmin: boolean;
};

export function SuppressionManager({
  initialEntries,
  syncStatus,
  isAdmin,
}: SuppressionManagerProps) {
  const [entries, setEntries] = useState<SuppressionEntry[]>(initialEntries);
  const [revealedEmailsById, setRevealedEmailsById] = useState<Record<string, string>>({});
  const [isExporting, setIsExporting] = useState(false);
  const [revealingIds, setRevealingIds] = useState<Set<string>>(new Set());

  // Filters
  const [search, setSearch] = useState("");
  const [filterReason, setFilterReason] = useState<SuppressionReason | "">("");
  const [filterSource, setFilterSource] = useState<SuppressionSource | "">("");
  const [filterFrom, setFilterFrom] = useState("");
  const [filterTo, setFilterTo] = useState("");
  const [page, setPage] = useState(0);

  // Add single
  const [addOpen, setAddOpen] = useState(false);
  const [addEmail, setAddEmail] = useState("");
  const [addReason, setAddReason] = useState<SuppressionReason>("manual");
  const [addNote, setAddNote] = useState("");
  const [isAdding, setIsAdding] = useState(false);

  // Bulk add
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkRaw, setBulkRaw] = useState("");
  const [bulkReason, setBulkReason] = useState<SuppressionReason>("manual");
  const [isBulkAdding, setIsBulkAdding] = useState(false);

  // Remove
  const [removeTarget, setRemoveTarget] = useState<SuppressionEntry | null>(null);
  const [removeJustification, setRemoveJustification] = useState("");
  const [isRemoving, setIsRemoving] = useState(false);

  // Filtered + paginated
  const filtered = useMemo(() => {
    return entries.filter((e) => {
      if (search && !e.email.toLowerCase().includes(search.toLowerCase())) return false;
      if (filterReason && e.reason !== filterReason) return false;
      if (filterSource && e.source !== filterSource) return false;
      if (filterFrom && e.createdAt < filterFrom) return false;
      if (filterTo && e.createdAt > filterTo + "T23:59:59Z") return false;
      return true;
    });
  }, [entries, search, filterReason, filterSource, filterFrom, filterTo]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const pageEntries = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function resetPage() {
    setPage(0);
  }

  async function handleExportCsv() {
    if (!isAdmin || isExporting) return;
    setIsExporting(true);
    try {
      const response = await fetch(
        new URL(apiEndpoints.suppression.export, publicEnv.NEXT_PUBLIC_API_BASE_URL),
        {
          method: "POST",
          credentials: "include",
          headers: {
            Accept: "text/csv",
          },
        },
      );
      if (!response.ok) {
        throw new Error("Export failed");
      }
      const blob = await response.blob();
      downloadCsvBlob(blob, "suppression-export.csv");
      toast.success("Suppression CSV exported.");
    } catch {
      toast.error("Failed to export suppression CSV.");
    } finally {
      setIsExporting(false);
    }
  }

  async function handleReveal(entry: SuppressionEntry) {
    if (!isAdmin || revealingIds.has(entry.id)) return;
    setRevealingIds((prev) => new Set([...prev, entry.id]));
    try {
      const revealed = await clientJson<ApiSuppressionRevealResponse>(
        apiEndpoints.suppression.reveal(entry.id),
        {
          method: "GET",
        },
      );
      setRevealedEmailsById((prev) => ({ ...prev, [entry.id]: revealed.email }));
      toast.success("Email revealed.");
    } catch {
      toast.error("Failed to reveal email.");
    } finally {
      setRevealingIds((prev) => {
        const next = new Set(prev);
        next.delete(entry.id);
        return next;
      });
    }
  }

  async function handleAdd() {
    if (!addEmail.trim()) return;
    setIsAdding(true);
    try {
      const created = await clientJson<SuppressionEntry>(
        apiEndpoints.suppression.create,
        {
          method: "POST",
          body: {
            email: addEmail.trim().toLowerCase(),
            reason: addReason,
            note: addNote.trim() || null,
          },
        },
      );
      setEntries((prev) => [created, ...prev]);
      setAddOpen(false);
      setAddEmail("");
      setAddNote("");
      toast.success(`${addEmail.trim()} added to suppression list.`);
    } catch {
      toast.error("Failed to add entry. Check the email and try again.");
    } finally {
      setIsAdding(false);
    }
  }

  async function handleBulkAdd() {
    const emails = parseEmailList(bulkRaw);
    if (emails.length === 0) return;
    setIsBulkAdding(true);
    try {
      const created = await clientJson<SuppressionEntry[]>(
        apiEndpoints.suppression.bulkImport,
        {
          method: "POST",
          body: { emails, reason: bulkReason },
        },
      );
      setEntries((prev) => [...created, ...prev]);
      setBulkOpen(false);
      setBulkRaw("");
      toast.success(`${created.length} address(es) added to suppression list.`);
    } catch {
      toast.error("Bulk add failed. Please try again.");
    } finally {
      setIsBulkAdding(false);
    }
  }

  async function handleRemove() {
    if (!removeTarget || !removeJustification.trim()) return;
    setIsRemoving(true);
    try {
      await clientJson(apiEndpoints.suppression.remove(removeTarget.email), {
        method: "DELETE",
        body: { justification: removeJustification.trim() },
      });
      setEntries((prev) => prev.filter((e) => e.id !== removeTarget.id));
      toast.success(
        `${maskEmailAddress(removeTarget.email)} removed. Audit entry recorded.`,
      );
      setRemoveTarget(null);
      setRemoveJustification("");
    } catch {
      toast.error("Removal failed. Please try again.");
    } finally {
      setIsRemoving(false);
    }
  }

  const bulkEmails = parseEmailList(bulkRaw);

  return (
    <div className="grid gap-6">
      {/* SES sync panel */}
      <div className="surface-panel-muted rounded-lg px-5 py-4 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">SES suppression sync</p>
          <p className="text-xs text-text-muted mt-0.5">
            Last synced:{" "}
            {syncStatus.lastSyncAt
              ? formatTimestamp(syncStatus.lastSyncAt)
              : "Never"}
          </p>
        </div>
        {syncStatus.driftCount > 0 ? (
          <Badge variant="warning">
            {syncStatus.driftCount} drift{syncStatus.driftCount !== 1 ? "s" : ""}
          </Badge>
        ) : (
          <Badge variant="success">In sync</Badge>
        )}
      </div>

      {/* Action bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-text-muted">
          {filtered.length.toLocaleString()} entr
          {filtered.length !== 1 ? "ies" : "y"}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!isAdmin || isExporting}
            onClick={() => void handleExportCsv()}
          >
            {isExporting ? "Exporting…" : "Export CSV"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setBulkOpen(true)}
          >
            Bulk add
          </Button>
          <Button type="button" size="sm" onClick={() => setAddOpen(true)}>
            Add entry
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <div
        className="flex flex-wrap gap-3"
        role="search"
        aria-label="Suppression filters"
      >
        <Input
          type="search"
          placeholder="Search email…"
          aria-label="Search by email"
          className="h-9 min-w-48 max-w-xs"
          value={search}
          onChange={(e) => { setSearch(e.target.value); resetPage(); }}
        />
        <select
          className="field h-9"
          aria-label="Filter by reason"
          value={filterReason}
          onChange={(e) => { setFilterReason(e.target.value as SuppressionReason | ""); resetPage(); }}
        >
          <option value="">All reasons</option>
          {ALL_REASONS.map((r) => (
            <option key={r} value={r}>
              {SUPPRESSION_REASON_LABELS[r]}
            </option>
          ))}
        </select>
        <select
          className="field h-9"
          aria-label="Filter by source"
          value={filterSource}
          onChange={(e) => { setFilterSource(e.target.value as SuppressionSource | ""); resetPage(); }}
        >
          <option value="">All sources</option>
          {ALL_SOURCES.map((s) => (
            <option key={s} value={s}>
              {SUPPRESSION_SOURCE_LABELS[s]}
            </option>
          ))}
        </select>
        <div className="flex items-center gap-2">
          <label className="text-xs text-text-muted" htmlFor="filter-from">
            From
          </label>
          <input
            id="filter-from"
            type="date"
            className="field h-9 text-sm"
            aria-label="Filter from date"
            value={filterFrom}
            onChange={(e) => { setFilterFrom(e.target.value); resetPage(); }}
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-text-muted" htmlFor="filter-to">
            To
          </label>
          <input
            id="filter-to"
            type="date"
            className="field h-9 text-sm"
            aria-label="Filter to date"
            value={filterTo}
            onChange={(e) => { setFilterTo(e.target.value); resetPage(); }}
          />
        </div>
      </div>

      {/* Table */}
      <div className="surface-panel overflow-hidden">
        <table className="w-full text-sm" aria-label="Suppression list">
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="px-4 py-3 text-left font-medium text-text-muted">
                Email
              </th>
              <th scope="col" className="px-4 py-3 text-left font-medium text-text-muted">
                Reason
              </th>
              <th scope="col" className="px-4 py-3 text-left font-medium text-text-muted">
                Source
              </th>
              <th scope="col" className="px-4 py-3 text-left font-medium text-text-muted">
                First seen
              </th>
              {isAdmin ? (
                <th scope="col" className="px-4 py-3 text-right font-medium text-text-muted">
                  Actions
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {pageEntries.length === 0 ? (
              <tr>
                <td
                  colSpan={isAdmin ? 5 : 4}
                  className="px-4 py-10 text-center text-sm text-text-muted"
                >
                  No suppression entries match the current filters.
                </td>
              </tr>
            ) : (
              pageEntries.map((entry) => {
                const revealedEmail = revealedEmailsById[entry.id] ?? null;
                const isRevealed = revealedEmail !== null;
                const displayEmail = isRevealed ? revealedEmail : maskEmailAddress(entry.email);
                return (
                  <tr
                    key={entry.id}
                    className="border-b border-border last:border-0 hover:bg-surface-muted/50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="mono text-xs">{displayEmail}</span>
                        {isAdmin && !isRevealed ? (
                          <button
                            type="button"
                            className="text-xs text-primary underline underline-offset-2 hover:no-underline"
                            disabled={revealingIds.has(entry.id)}
                            onClick={() => void handleReveal(entry)}
                          >
                            {revealingIds.has(entry.id) ? "Revealing…" : "Reveal"}
                          </button>
                        ) : null}
                      </div>
                      {entry.note ? (
                        <p className="text-xs text-text-muted mt-0.5">{entry.note}</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={SUPPRESSION_REASON_VARIANTS[entry.reason]}>
                        {SUPPRESSION_REASON_LABELS[entry.reason]}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted">
                      {SUPPRESSION_SOURCE_LABELS[entry.source]}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted">
                      {formatTimestamp(entry.createdAt)}
                    </td>
                    {isAdmin ? (
                      <td className="px-4 py-3 text-right">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            setRemoveTarget(entry);
                            setRemoveJustification("");
                          }}
                          aria-label={`Remove ${displayEmail} from suppression list`}
                        >
                          Remove
                        </Button>
                      </td>
                    ) : null}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-text-muted">
            Showing {page * PAGE_SIZE + 1}–
            {Math.min((page + 1) * PAGE_SIZE, filtered.length)} of{" "}
            {filtered.length.toLocaleString()}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}

      {/* Single-add dialog */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add suppression entry</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="label" htmlFor="add-email">
                Email address
              </label>
              <Input
                id="add-email"
                type="email"
                value={addEmail}
                onChange={(e) => setAddEmail(e.target.value)}
                placeholder="address@example.com"
                autoFocus
              />
            </div>
            <div>
              <label className="label" htmlFor="add-reason">
                Reason
              </label>
              <select
                id="add-reason"
                className="field h-9 w-full"
                value={addReason}
                onChange={(e) => setAddReason(e.target.value as SuppressionReason)}
              >
                {ALL_REASONS.map((r) => (
                  <option key={r} value={r}>
                    {SUPPRESSION_REASON_LABELS[r]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="add-note">
                Note{" "}
                <span className="font-normal text-text-muted">(optional)</span>
              </label>
              <Input
                id="add-note"
                value={addNote}
                onChange={(e) => setAddNote(e.target.value)}
                placeholder="Context for the audit trail"
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAddOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!addEmail.trim() || isAdding}
              onClick={() => void handleAdd()}
            >
              {isAdding ? "Adding…" : "Add"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk-add dialog */}
      <Dialog open={bulkOpen} onOpenChange={setBulkOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Bulk add suppression entries</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="label" htmlFor="bulk-emails">
                Email addresses
              </label>
              <textarea
                id="bulk-emails"
                className="field min-h-32 text-sm"
                value={bulkRaw}
                onChange={(e) => setBulkRaw(e.target.value)}
                placeholder={"alice@example.com\nbob@example.com\n…"}
                spellCheck={false}
              />
              <p className="mt-1 text-xs text-text-muted">
                One per line or comma-separated. Duplicates are removed
                automatically.
              </p>
              {bulkRaw.trim() ? (
                <p className="mt-1 text-xs font-medium">
                  {bulkEmails.length} valid address
                  {bulkEmails.length !== 1 ? "es" : ""} parsed
                </p>
              ) : null}
            </div>
            <div>
              <label className="label" htmlFor="bulk-reason">
                Reason
              </label>
              <select
                id="bulk-reason"
                className="field h-9 w-full"
                value={bulkReason}
                onChange={(e) => setBulkReason(e.target.value as SuppressionReason)}
              >
                {ALL_REASONS.map((r) => (
                  <option key={r} value={r}>
                    {SUPPRESSION_REASON_LABELS[r]}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setBulkOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={bulkEmails.length === 0 || isBulkAdding}
              onClick={() => void handleBulkAdd()}
            >
              {isBulkAdding
                ? "Adding…"
                : `Add ${bulkEmails.length} address${bulkEmails.length !== 1 ? "es" : ""}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Remove confirm dialog — admin only, requires justification */}
      <Dialog
        open={removeTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRemoveTarget(null);
            setRemoveJustification("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove from suppression list</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <p className="text-sm text-text-muted">
              You are about to remove{" "}
              <span className="mono font-medium text-foreground">
                {removeTarget ? maskEmailAddress(removeTarget.email) : ""}
              </span>{" "}
              from the suppression list. This action is audited and irreversible
              without re-adding.
            </p>
            <div>
              <label className="label" htmlFor="remove-justification">
                Justification <span className="text-danger">*</span>
              </label>
              <Input
                id="remove-justification"
                value={removeJustification}
                onChange={(e) => setRemoveJustification(e.target.value)}
                placeholder="e.g. User requested re-subscription after confirming consent"
                autoFocus
              />
              <p className="mt-1 text-xs text-text-muted">
                Required — written to the audit log.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setRemoveTarget(null);
                setRemoveJustification("");
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!removeJustification.trim() || isRemoving}
              onClick={() => void handleRemove()}
            >
              {isRemoving ? "Removing…" : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
