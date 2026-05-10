import type { MergeTag, Template, TemplateVersion } from "@/types/template";

export type ApiTemplateVersionResponse = {
  id: string;
  template_id: string;
  version_number: number;
  subject: string;
  body_text: string;
  body_html: string | null;
  is_published: boolean;
  created_at: string;
};

export type ApiTemplateResponse = {
  id: string;
  name: string;
  description: string | null;
  head_version_number: number | null;
  created_at: string;
  updated_at: string;
  versions: ApiTemplateVersionResponse[];
};

export type ApiTemplateListResponse = {
  items: ApiTemplateResponse[];
};

export type ApiMergeTagResponse = {
  tag: string;
  label: string;
};

export function toTemplate(api: ApiTemplateResponse): Template {
  return {
    id: api.id,
    name: api.name,
    description: api.description,
    activeVersion: api.head_version_number,
    createdAt: api.created_at,
    updatedAt: api.updated_at,
  };
}

export function toTemplateVersion(api: ApiTemplateVersionResponse): TemplateVersion {
  return {
    id: api.id,
    templateId: api.template_id,
    version: api.version_number,
    subject: api.subject,
    bodyText: api.body_text,
    bodyHtml: api.body_html ?? "",
    publishedAt: api.is_published ? api.created_at : null,
    createdAt: api.created_at,
  };
}

export function toMergeTag(api: ApiMergeTagResponse): MergeTag {
  return {
    tag: api.tag,
    label: api.label,
  };
}

