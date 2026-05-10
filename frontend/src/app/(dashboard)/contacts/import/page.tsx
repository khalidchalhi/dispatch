"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { buildInitialMapping } from "./_components/mapping-step";
import { MappingStep } from "./_components/mapping-step";
import { ProgressStep } from "./_components/progress-step";
import { ReviewStep } from "./_components/review-step";
import { UploadStep } from "./_components/upload-step";
import type { ParsedFile } from "./_components/upload-step";
import type { ApiImportJobResponse } from "./_lib/import-api";
import type { ColumnMapping } from "@/types/import";
import type { ImportJob } from "@/types/import";

type WizardStep = "upload" | "mapping" | "progress" | "review";

const STEP_LABELS: Record<WizardStep, string> = {
  upload: "Upload",
  mapping: "Column mapping",
  progress: "Progress",
  review: "Review errors",
};

const STEP_ORDER: WizardStep[] = ["upload", "mapping", "progress", "review"];

function WizardNav({ current }: { current: WizardStep }) {
  const currentIndex = STEP_ORDER.indexOf(current);
  return (
    <nav aria-label="Import wizard steps">
      <ol className="flex flex-wrap items-center gap-2">
        {STEP_ORDER.map((step, i) => {
          const done = i < currentIndex;
          const active = step === current;
          return (
            <li key={step} className="flex items-center gap-2">
              {i > 0 ? (
                <span aria-hidden="true" className="text-text-muted">
                  /
                </span>
              ) : null}
              <span
                aria-current={active ? "step" : undefined}
                className={`text-sm font-medium ${
                  active
                    ? "text-foreground"
                    : done
                      ? "text-text-muted line-through"
                      : "text-text-muted"
                }`}
              >
                {STEP_LABELS[step]}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export default function ContactImportPage() {
  const [step, setStep] = useState<WizardStep>("upload");
  const [parsed, setParsed] = useState<ParsedFile | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping>({});
  const [jobId, setJobId] = useState<string | null>(null);
  const [completedJob, setCompletedJob] = useState<ImportJob | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Block browser tab close / reload while import is in flight
  useEffect(() => {
    if (step !== "progress") return;
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [step]);

  function handleParsed(p: ParsedFile) {
    setParsed(p);
    setMapping(buildInitialMapping(p.headers));
    setStep("mapping");
  }

  async function handleSubmit(finalMapping: ColumnMapping) {
    if (!parsed) return;
    setIsSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("file", parsed.file);
      formData.append("mapping", JSON.stringify(finalMapping));
      const job = await clientJson<ApiImportJobResponse>(apiEndpoints.contacts.bulkImport, {
        method: "POST",
        body: formData,
      });
      setMapping(finalMapping);
      setJobId(job.id);
      setStep("progress");
    } catch {
      toast.error("Upload failed. Check the file and try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  const handleComplete = useCallback((job: ImportJob) => {
    setCompletedJob(job);
    if (job.status === "completed") {
      setStep("review");
    }
  }, []);

  function reset() {
    setParsed(null);
    setMapping({});
    setJobId(null);
    setCompletedJob(null);
    setStep("upload");
  }

  return (
    <div className="page-stack">
      <nav
        className="flex items-center gap-2 text-sm text-text-muted"
        aria-label="Breadcrumb"
      >
        <Link href="/contacts" className="hover:underline">
          Contacts
        </Link>
        <span aria-hidden="true">/</span>
        <span>Import</span>
      </nav>

      <header className="page-intro">
        <div className="page-intro-copy">
          <h1 className="page-title">Import contacts</h1>
          <p className="page-description">
            Upload a CSV file, map columns to contact fields, and track
            validation progress. Rejections can be reviewed and exported.
          </p>
        </div>
      </header>

      <WizardNav current={step} />

      <section className="surface-panel p-6">
        {step === "upload" ? (
          <UploadStep onParsed={handleParsed} />
        ) : step === "mapping" && parsed ? (
          <MappingStep
            headers={parsed.headers}
            initialMapping={mapping}
            onBack={() => setStep("upload")}
            onSubmit={handleSubmit}
            isSubmitting={isSubmitting}
          />
        ) : step === "progress" && jobId && parsed ? (
          <ProgressStep
            jobId={jobId}
            fileName={parsed.file.name}
            onComplete={handleComplete}
          />
        ) : step === "review" && completedJob ? (
          <ReviewStep job={completedJob} />
        ) : (
          // Fallback: reset to upload if state is inconsistent
          <div className="py-8 text-center">
            <p className="mb-4 text-sm text-text-muted">
              Something went wrong with the wizard state.
            </p>
            <button
              type="button"
              className="text-sm text-primary underline underline-offset-2"
              onClick={reset}
            >
              Start over
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
