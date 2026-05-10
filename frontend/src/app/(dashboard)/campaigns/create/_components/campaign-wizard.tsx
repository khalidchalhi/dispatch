"use client";

import { useState, useEffect } from "react";
import { WizardNav } from "./wizard-nav";
import { StepDetails } from "./step-details";
import { StepSender } from "./step-sender";
import { StepTemplate } from "./step-template";
import { StepAudience } from "./step-audience";
import { StepSchedule } from "./step-schedule";
import { StepReview } from "./step-review";
import { EMPTY_DRAFT } from "@/types/campaign";
import type { CampaignDraft } from "@/types/campaign";
import type { WizardData } from "../_lib/wizard-types";

const STORAGE_KEY = "dispatch:campaign-draft";

function loadDraft(): CampaignDraft {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...EMPTY_DRAFT, ...(JSON.parse(raw) as Partial<CampaignDraft>) };
  } catch {
    // ignore
  }
  return { ...EMPTY_DRAFT };
}

function saveDraft(draft: CampaignDraft) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
  } catch {
    // ignore
  }
}

function clearDraft() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

type CampaignWizardProps = WizardData;

export function CampaignWizard({ senderProfiles, templates, segments, lists }: CampaignWizardProps) {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<CampaignDraft>(() => loadDraft());

  useEffect(() => {
    saveDraft(draft);
  }, [draft]);

  function handleChange(patch: Partial<CampaignDraft>) {
    setDraft((prev) => ({ ...prev, ...patch }));
  }

  function handleNext() {
    setStep((s) => Math.min(s + 1, 5));
  }

  function handleBack() {
    setStep((s) => Math.max(s - 1, 0));
  }

  function handleGoToStep(target: number) {
    setStep(target);
  }

  function handleLaunchSuccess() {
    clearDraft();
    setDraft({ ...EMPTY_DRAFT });
    setStep(0);
  }

  return (
    <div className="grid gap-6">
      <WizardNav currentStep={step} />

      {step === 0 && (
        <StepDetails
          draft={draft}
          onChange={handleChange}
          onNext={handleNext}
        />
      )}
      {step === 1 && (
        <StepSender
          draft={draft}
          senderProfiles={senderProfiles}
          onChange={handleChange}
          onBack={handleBack}
          onNext={handleNext}
        />
      )}
      {step === 2 && (
        <StepTemplate
          draft={draft}
          templates={templates}
          onChange={handleChange}
          onBack={handleBack}
          onNext={handleNext}
        />
      )}
      {step === 3 && (
        <StepAudience
          draft={draft}
          segments={segments}
          lists={lists}
          onChange={handleChange}
          onBack={handleBack}
          onNext={handleNext}
        />
      )}
      {step === 4 && (
        <StepSchedule
          draft={draft}
          onChange={handleChange}
          onBack={handleBack}
          onNext={handleNext}
        />
      )}
      {step === 5 && (
        <StepReview
          draft={draft}
          senderProfiles={senderProfiles}
          templates={templates}
          segments={segments}
          lists={lists}
          onChange={handleChange}
          onBack={handleBack}
          onGoToStep={handleGoToStep}
          onLaunchSuccess={handleLaunchSuccess}
        />
      )}
    </div>
  );
}
