import Link from "next/link";
import { notFound } from "next/navigation";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/errors";
import { TemplateWorkspace } from "../_components/template-workspace";
import {
  toMergeTag,
  toTemplate,
  toTemplateVersion,
  type ApiMergeTagResponse,
  type ApiTemplateResponse,
} from "../_lib/templates-api";

type TemplateDetailPageProps = {
  params: Promise<{ templateId: string }>;
};

export default async function TemplateDetailPage({
  params,
}: TemplateDetailPageProps) {
  const { templateId } = await params;

  let templateResponse: ApiTemplateResponse;
  try {
    templateResponse = await serverJson<ApiTemplateResponse>(
      ENDPOINTS.templates.byId(templateId),
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  const mergeTagsResponse = await serverJson<ApiMergeTagResponse[]>(
    ENDPOINTS.templates.mergeTags,
  );

  const template = toTemplate(templateResponse);
  const versions = templateResponse.versions.map(toTemplateVersion);
  const mergeTags = mergeTagsResponse.map(toMergeTag);

  return (
    <div className="page-stack">
      <nav
        className="flex items-center gap-2 text-sm text-text-muted"
        aria-label="Breadcrumb"
      >
        <Link href="/templates" className="hover:underline">
          Templates
        </Link>
        <span aria-hidden="true">/</span>
        <span>{template.name}</span>
      </nav>

      <header className="page-intro">
        <div className="page-intro-copy">
          <h1 className="page-title">{template.name}</h1>
          {template.description ? (
            <p className="page-description">{template.description}</p>
          ) : null}
        </div>
      </header>

      <TemplateWorkspace
        template={template}
        versions={versions}
        mergeTags={mergeTags}
      />
    </div>
  );
}
