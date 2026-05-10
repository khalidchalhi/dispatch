"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { TemplateEditor } from "./template-editor";
import { PreviewPane } from "./preview-pane";
import { VersionHistory } from "./version-history";
import type { Template, TemplateVersion, MergeTag } from "@/types/template";
import { toTemplateVersion, type ApiTemplateResponse } from "../_lib/templates-api";

type Draft = {
  subject: string;
  bodyText: string;
  bodyHtml: string;
};

type TemplateWorkspaceProps = {
  template: Template;
  versions: TemplateVersion[];
  mergeTags: MergeTag[];
};

export function TemplateWorkspace({
  template,
  versions: initialVersions,
  mergeTags,
}: TemplateWorkspaceProps) {
  const [activeVersion, setActiveVersion] = useState<number | null>(
    template.activeVersion,
  );
  const [versions, setVersions] = useState<TemplateVersion[]>(initialVersions);
  const [isSaving, setIsSaving] = useState(false);
  const [publishingVersionId, setPublishingVersionId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<TemplateVersion | null>(
    () => {
      const active = initialVersions.find(
        (v) => v.version === activeVersion,
      );
      return active ?? initialVersions.at(-1) ?? null;
    },
  );
  const [previewDraft, setPreviewDraft] = useState<Draft>({
    subject: selectedVersion?.subject ?? "",
    bodyText: selectedVersion?.bodyText ?? "",
    bodyHtml: selectedVersion?.bodyHtml ?? "",
  });

  const handleDraftChange = useCallback((draft: Draft) => {
    setPreviewDraft(draft);
  }, []);

  async function handleSave(draft: Draft) {
    setIsSaving(true);
    try {
      const response = await clientJson<ApiTemplateResponse>(
        apiEndpoints.templates.versions(template.id),
        {
          method: "POST",
          body: {
            subject: draft.subject,
            body_text: draft.bodyText,
            body_html: draft.bodyHtml || null,
          },
        },
      );
      const mappedVersions = response.versions.map(toTemplateVersion);
      setVersions(mappedVersions);
      setActiveVersion(response.head_version_number);
      const nextSelected = mappedVersions.at(-1) ?? null;
      setSelectedVersion(nextSelected);
      if (nextSelected) {
        toast.success(`Version v${nextSelected.version} saved.`);
      } else {
        toast.success("Version saved.");
      }
    } catch {
      toast.error("Failed to save version. Please try again.");
    } finally {
      setIsSaving(false);
    }
  }

  async function handlePublish(version: TemplateVersion) {
    setPublishingVersionId(version.id);
    try {
      const response = await clientJson<ApiTemplateResponse>(
        apiEndpoints.templates.publishVersion(template.id, String(version.version)),
        {
          method: "POST",
        },
      );
      const mappedVersions = response.versions.map(toTemplateVersion);
      setVersions(mappedVersions);
      setActiveVersion(response.head_version_number);
      const nextSelected =
        mappedVersions.find((item) => item.version === version.version) ??
        mappedVersions.at(-1) ??
        null;
      setSelectedVersion(nextSelected);
      toast.success(`Version v${version.version} published.`);
    } catch {
      toast.error("Failed to publish version. Please try again.");
    } finally {
      setPublishingVersionId(null);
    }
  }

  return (
    <div className="grid gap-5">
      <div className="flex justify-end">
        <button
          type="button"
          className="text-sm text-primary underline underline-offset-2 hover:no-underline"
          onClick={() => setShowHistory((v) => !v)}
          aria-expanded={showHistory}
        >
          {showHistory ? "Hide version history" : "Show version history"}
        </button>
      </div>

      {showHistory ? (
        <VersionHistory
          versions={versions}
          activeVersion={activeVersion}
          onPublish={handlePublish}
          publishingVersionId={publishingVersionId}
          onSelect={setSelectedVersion}
          selectedVersion={selectedVersion}
        />
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <TemplateEditor
          templateId={template.id}
          initialVersion={selectedVersion}
          mergeTags={mergeTags}
          isSaving={isSaving}
          onSave={handleSave}
          onDraftChange={handleDraftChange}
        />
        <PreviewPane
          subject={previewDraft.subject}
          bodyHtml={previewDraft.bodyHtml}
          bodyText={previewDraft.bodyText}
        />
      </div>
    </div>
  );
}
