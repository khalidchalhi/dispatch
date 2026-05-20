"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { toDnsZones } from "@/app/(dashboard)/domains/_lib/provisioning-api";
import type { DnsZone, DomainListItem, ProvisioningProvider } from "@/types/domain";

const HOSTNAME_RE = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$/i;

type StepId = "provider" | "name" | "auth" | "zones" | "confirm";

function getSteps(provider: ProvisioningProvider | null): StepId[] {
  if (!provider || provider === "manual") {
    return ["provider", "name", "confirm"];
  }
  return ["provider", "name", "auth", "zones", "confirm"];
}

const PROVIDER_OPTIONS: {
  id: ProvisioningProvider;
  label: string;
  badge?: string;
  description: string;
}[] = [
  {
    id: "manual",
    label: "Manual",
    description: "Generate DNS records and add them yourself.",
  },
  {
    id: "cloudflare",
    label: "Cloudflare",
    badge: "Automated",
    description: "Dispatch writes DNS records via Cloudflare API.",
  },
  {
    id: "route53",
    label: "Route 53",
    badge: "Automated",
    description: "Dispatch writes DNS records via AWS Route 53.",
  },
];

type AuthStatus = "ok" | "error";

const MOCK_AUTH: Record<Exclude<ProvisioningProvider, "manual">, AuthStatus> = {
  cloudflare: "ok",
  route53: "ok",
};

export function ProvisioningWizard() {
  const router = useRouter();
  const [stepIdx, setStepIdx] = useState(0);
  const [provider, setProvider] = useState<ProvisioningProvider | null>(null);
  const [domainName, setDomainName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [zoneId, setZoneId] = useState<string | null>(null);
  const [zones, setZones] = useState<DnsZone[]>([]);
  const [isLoadingZones, setIsLoadingZones] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const zoneRequestId = useRef(0);

  const steps = useMemo(() => getSteps(provider), [provider]);
  const currentStep = steps[stepIdx]!;
  const totalSteps = steps.length;

  async function loadProviderZones(nextProvider: Exclude<ProvisioningProvider, "manual">) {
    const requestId = zoneRequestId.current + 1;
    zoneRequestId.current = requestId;
    setIsLoadingZones(true);

    try {
      const response = await clientJson<unknown>(apiEndpoints.domains.zones(nextProvider));
      if (zoneRequestId.current !== requestId) return;
      setZones(toDnsZones(response, nextProvider));
    } catch {
      if (zoneRequestId.current !== requestId) return;
      setZones([]);
      toast.error("Could not load provider zones. Please retry.");
    } finally {
      if (zoneRequestId.current === requestId) setIsLoadingZones(false);
    }
  }

  function resetProviderZones() {
    zoneRequestId.current += 1;
    setZones([]);
    setIsLoadingZones(false);
  }

  function handleProviderSelect(p: ProvisioningProvider) {
    setProvider(p);
    setZoneId(null);
    setStepIdx(1);
    if (p === "manual") {
      resetProviderZones();
      return;
    }
    void loadProviderZones(p);
  }

  function handleBack() {
    if (stepIdx === 0) return;
    setStepIdx((i) => i - 1);
  }

  function validateAndNext() {
    if (currentStep === "name") {
      const trimmed = domainName.trim();
      if (!trimmed) {
        setNameError("Enter the fully-qualified domain name to send from.");
        return;
      }
      if (!HOSTNAME_RE.test(trimmed)) {
        setNameError("Enter a valid domain name, e.g. mail.example.com.");
        return;
      }
      setNameError(null);
    }

    if (currentStep === "zones" && !zoneId) {
      return;
    }

    setStepIdx((i) => i + 1);
  }

  async function handleSubmit() {
    setIsSubmitting(true);
    try {
      const domain = await clientJson<DomainListItem>(
        apiEndpoints.domains.create,
        {
          method: "POST",
          body: {
            name: domainName.trim(),
            dns_provider: provider ?? "manual",
            ...(provider === "cloudflare" && zoneId
              ? { cloudflare_zone_id: zoneId }
              : {}),
            ...(provider === "route53" && zoneId
              ? { route53_hosted_zone_id: zoneId }
              : {}),
          },
        },
      );

      if (provider === "manual") {
        toast.success(
          "Domain added. Set up the DNS records to start verification.",
        );
        router.push(`/domains/${domain.id}`);
      } else {
        toast.success("Provisioning started.");
        router.push(`/domains/${domain.id}/provision`);
      }
    } catch {
      toast.error("Could not add domain. Check the name and try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  const authStatus =
    provider && provider !== "manual" ? MOCK_AUTH[provider] : null;

  const isLastStep = stepIdx === totalSteps - 1;
  const canGoNext =
    currentStep === "zones" ? zoneId !== null : currentStep !== "auth" || authStatus === "ok";

  return (
    <div className="surface-panel mx-auto max-w-xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <span className="text-sm text-text-muted">
          Step {stepIdx + 1} of {totalSteps}
        </span>
        <div className="flex items-center gap-1.5">
          {steps.map((_, i) => (
            <span
              key={i}
              className={`h-2 w-2 rounded-full transition-colors ${
                i < stepIdx
                  ? "bg-primary"
                  : i === stepIdx
                    ? "bg-primary ring-2 ring-primary/30"
                    : "bg-border"
              }`}
              aria-hidden
            />
          ))}
        </div>
      </div>

      <div className="grid gap-6">
        {currentStep === "provider" && (
          <section aria-label="Choose provisioning method">
            <h2 className="section-title mb-4">Choose provisioning method</h2>
            <div className="grid gap-3">
              {PROVIDER_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  aria-pressed={provider === opt.id}
                  onClick={() => handleProviderSelect(opt.id)}
                  className={`flex items-start gap-4 rounded-lg border p-4 text-left transition-colors hover:border-primary ${
                    provider === opt.id
                      ? "border-primary bg-primary/5"
                      : "border-border"
                  }`}
                >
                  <div className="flex-1 grid gap-0.5">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{opt.label}</span>
                      {opt.badge && (
                        <Badge variant="success">{opt.badge}</Badge>
                      )}
                    </div>
                    <p className="text-sm text-text-muted">{opt.description}</p>
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        {currentStep === "name" && (
          <section aria-label="Domain name">
            <h2 className="section-title mb-4">Domain name</h2>
            <div className="grid gap-1.5">
              <label htmlFor="wizard-domain-name" className="text-sm font-medium">
                Fully-qualified domain name
              </label>
              <input
                id="wizard-domain-name"
                type="text"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                placeholder="mail.example.com"
                value={domainName}
                onChange={(e) => {
                  setDomainName(e.target.value);
                  setNameError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") validateAndNext();
                }}
                className="h-9 rounded-md border border-border bg-background px-3 text-sm placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-[color:var(--focus-ring)]"
              />
              {nameError && (
                <p className="text-sm text-danger" role="alert">
                  {nameError}
                </p>
              )}
            </div>
          </section>
        )}

        {currentStep === "auth" && provider && provider !== "manual" && (
          <section aria-label="Provider authorization">
            <h2 className="section-title mb-4">Authorization</h2>
            <div className="surface-panel-muted rounded-lg p-4">
              <div className="flex items-center gap-3">
                {authStatus === "ok" ? (
                  <CheckCircle2 className="h-5 w-5 text-success shrink-0" aria-hidden />
                ) : (
                  <AlertCircle className="h-5 w-5 text-danger shrink-0" aria-hidden />
                )}
                <div>
                  <p className="text-sm font-medium">
                    {provider === "cloudflare"
                      ? "Cloudflare API token"
                      : "AWS IAM role"}
                  </p>
                  <p className="text-xs text-text-muted">
                    {authStatus === "ok"
                      ? provider === "cloudflare"
                        ? "API token is configured with Zone:Edit permission."
                        : "IAM role is assumable by the dispatch service account."
                      : "Credentials not configured. Contact a platform admin."}
                  </p>
                </div>
              </div>
            </div>
            <p className="mt-3 text-xs text-text-muted">
              Provider credentials are stored server-side only and are never
              exposed in the client bundle or network responses.
            </p>
          </section>
        )}

        {currentStep === "zones" && (
          <section aria-label="Zone selection">
            <h2 className="section-title mb-4">Select DNS zone</h2>
            {isLoadingZones ? (
              <p className="text-sm text-text-muted">Loading zones…</p>
            ) : zones.length === 0 ? (
              <p className="text-sm text-text-muted">
                No zones returned for this provider.
              </p>
            ) : (
              <div className="grid gap-2" role="radiogroup" aria-label="DNS zone">
              {zones.map((zone) => (
                <label
                  key={zone.id}
                  className={`flex items-center gap-3 rounded-lg border p-3 cursor-pointer transition-colors hover:border-primary ${
                    zoneId === zone.id ? "border-primary bg-primary/5" : "border-border"
                  }`}
                >
                  <input
                    type="radio"
                    name="dns-zone"
                    value={zone.id}
                    checked={zoneId === zone.id}
                    onChange={() => setZoneId(zone.id)}
                    className="sr-only"
                  />
                  <span className="text-sm font-medium">{zone.name}</span>
                  <Badge variant="outline" className="ml-auto">
                    {zone.provider}
                  </Badge>
                </label>
              ))}
              </div>
            )}
          </section>
        )}

        {currentStep === "confirm" && (
          <section aria-label="Confirm provisioning">
            <h2 className="section-title mb-4">Confirm</h2>
            <div className="surface-panel-muted grid gap-2 rounded-lg p-4 text-sm">
              <div className="flex justify-between">
                <span className="text-text-muted">Method</span>
                <span className="font-medium capitalize">
                  {provider ?? "manual"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">Domain</span>
                <span className="font-mono font-medium">{domainName.trim()}</span>
              </div>
              {zoneId && zones.length > 0 && (
                <div className="flex justify-between">
                  <span className="text-text-muted">Zone</span>
                  <span>
                    {zones.find((z) => z.id === zoneId)?.name ?? zoneId}
                  </span>
                </div>
              )}
            </div>
            <p className="mt-3 text-sm text-text-muted">
              {provider === "manual"
                ? "DNS records will be generated. Add them to your DNS provider to start verification."
                : "Dispatch will create DNS records automatically. You will be taken to the provisioning status page."}
            </p>
          </section>
        )}

        <div className="flex items-center justify-between pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={handleBack}
            disabled={stepIdx === 0 || isSubmitting}
          >
            Back
          </Button>

          {!isLastStep ? (
            <Button
              type="button"
              onClick={validateAndNext}
              disabled={!canGoNext}
            >
              Next
            </Button>
          ) : (
            <Button
              type="button"
              disabled={isSubmitting}
              onClick={() => void handleSubmit()}
            >
              {isSubmitting
                ? "Adding…"
                : provider === "manual"
                  ? "Create domain"
                  : "Provision"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
