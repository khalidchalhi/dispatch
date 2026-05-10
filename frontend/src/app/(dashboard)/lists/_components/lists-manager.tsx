"use client";

import { useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { formatTimestamp } from "@/lib/formatters";
import type { List } from "@/types/list";
import { toList, type ApiListResponse } from "../_lib/lists-api";

type ListsManagerProps = {
  initialLists: List[];
};

export function ListsManager({ initialLists }: ListsManagerProps) {
  const router = useRouter();
  const [lists, setLists] = useState(initialLists);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  function resetForm() {
    setName("");
    setDescription("");
    setNameError(null);
  }

  async function handleCreate() {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setNameError("List name is required.");
      return;
    }
    setIsPending(true);
    try {
      const created = await clientJson<ApiListResponse>(apiEndpoints.lists.create, {
        method: "POST",
        body: { name: trimmedName, description: description.trim() || null },
      });
      toast.success("List created.");
      setLists((prev) => [...prev, toList(created)]);
      setCreateOpen(false);
      resetForm();
      router.refresh();
    } catch {
      toast.error("Could not create list.");
    } finally {
      setIsPending(false);
    }
  }

  async function handleDelete(listId: string) {
    await clientJson(apiEndpoints.lists.delete(listId), { method: "DELETE" });
    toast.success("List deleted.");
    setLists((prev) => prev.filter((l) => l.id !== listId));
    router.refresh();
  }

  const createButton = (
    <Dialog
      open={createOpen}
      onOpenChange={(o) => {
        setCreateOpen(o);
        if (!o) resetForm();
      }}
    >
      <DialogTrigger asChild>
        <Button type="button">
          <Plus className="h-4 w-4" />
          Create list
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create list</DialogTitle>
          <DialogDescription>
            Lists group contacts for targeted campaign sends.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div>
            <label className="label" htmlFor="create-list-name">
              Name *
            </label>
            <Input
              id="create-list-name"
              type="text"
              placeholder="e.g. Early access"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNameError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleCreate();
              }}
            />
            {nameError ? (
              <p className="mt-2 text-sm text-danger">{nameError}</p>
            ) : null}
          </div>
          <div>
            <label className="label" htmlFor="create-list-description">
              Description
            </label>
            <Input
              id="create-list-description"
              type="text"
              placeholder="Optional"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="button"
            disabled={isPending}
            onClick={() => void handleCreate()}
          >
            {isPending ? "Creating…" : "Create list"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );

  if (lists.length === 0) {
    return (
      <>
        <EmptyState
          title="No lists yet"
          description="Create your first list to start organizing contacts for campaign sends."
          action={createButton}
        />
      </>
    );
  }

  return (
    <div className="grid gap-4">
      <div className="flex justify-end">{createButton}</div>
      <DataTable
        columns={[
          { key: "name", label: "Name" },
          { key: "members", label: "Members", className: "text-right" },
          { key: "updated", label: "Updated", className: "text-right" },
          { key: "actions", label: "", className: "text-right" },
        ]}
        rows={lists.map((l) => ({
          name: (
            <div>
              <Link
                href={`/lists/${l.id}`}
                className="font-medium hover:underline"
              >
                {l.name}
              </Link>
              {l.description ? (
                <p className="text-xs text-text-muted">{l.description}</p>
              ) : null}
            </div>
          ),
          members: (
            <Badge variant="muted">{l.memberCount.toLocaleString()}</Badge>
          ),
          updated: formatTimestamp(l.updatedAt),
          actions: (
            <ConfirmDialog
              title="Delete list"
              description={`Delete "${l.name}"? This removes the list but does not delete its contacts.`}
              trigger={
                <Button type="button" variant="outline" size="sm">
                  Delete
                </Button>
              }
              confirmLabel="Delete list"
              onConfirm={() => handleDelete(l.id)}
            />
          ),
        }))}
      />
    </div>
  );
}
