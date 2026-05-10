"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";
import type { DomainStatus } from "@/types/domain";

const POLL_INTERVAL_MS = 5_000;
const POLL_TIMEOUT_MS = 5 * 60 * 1_000;

type VerifyButtonProps = {
  domainId: string;
  initialStatus: DomainStatus;
};

type VerifyDomainResponse = {
  domain: {
    verification_status: string;
    reputation_status: string;
  };
  fully_verified: boolean;
  verified_records: number;
  total_records: number;
};

type DomainDetailStatusResponse = {
  verification_status: string;
  reputation_status: string;
};

function toDomainStatus(
  verificationStatus: string,
  reputationStatus: string,
): DomainStatus {
  if (reputationStatus === "retired") return "retired";
  if (reputationStatus === "burnt") return "burnt";
  if (reputationStatus === "cooling") return "cooling";
  if (verificationStatus === "verified") return "verified";
  if (verificationStatus === "pending") return "pending";
  return "verifying";
}

export function VerifyButton({ domainId, initialStatus }: VerifyButtonProps) {
  const [status, setStatus] = useState<DomainStatus>(initialStatus);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isVerifying = status === "verifying";
  const canVerify = status === "pending" || status === "verifying";

  useEffect(() => {
    if (!isVerifying) return;

    const startedAt = Date.now();
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    function scheduleNextPoll() {
      if (cancelled) return;

      const elapsed = Date.now() - startedAt;

      if (elapsed >= POLL_TIMEOUT_MS) {
        toast.error(
          "Verification timed out. DNS propagation can take up to 48 hours.",
        );
        return;
      }

      timeoutId = setTimeout(async () => {
        if (cancelled) return;

        try {
          const domain = await clientJson<DomainDetailStatusResponse>(
            apiEndpoints.domains.byId(domainId),
            { redirectOnUnauthorized: true },
          );

          if (!cancelled) {
            const polledStatus = toDomainStatus(
              domain.verification_status,
              domain.reputation_status,
            );
            setStatus(polledStatus);
            if (polledStatus === "verifying") {
              scheduleNextPoll();
            } else if (polledStatus === "verified") {
              toast.success("Domain verified successfully.");
            }
          }
        } catch {
          if (!cancelled) scheduleNextPoll();
        }
      }, POLL_INTERVAL_MS);
    }

    scheduleNextPoll();

    return () => {
      cancelled = true;
      if (timeoutId !== null) clearTimeout(timeoutId);
    };
  }, [isVerifying, domainId]);

  async function handleVerify() {
    setIsSubmitting(true);

    try {
      const result = await clientJson<VerifyDomainResponse>(
        apiEndpoints.domains.verify(domainId),
        {
          method: "POST",
          redirectOnUnauthorized: true,
        },
      );
      const nextStatus = toDomainStatus(
        result.domain.verification_status,
        result.domain.reputation_status,
      );
      setStatus(nextStatus);

      if (result.fully_verified || nextStatus === "verified") {
        toast.success(
          `Domain verified (${result.verified_records}/${result.total_records} records).`,
        );
      } else {
        toast.success(
          `Verification started (${result.verified_records}/${result.total_records} records verified).`,
        );
      }
    } catch {
      toast.error("Could not start verification. Try again in a moment.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!canVerify) return null;

  return (
    <Button
      type="button"
      variant={isVerifying ? "outline" : "default"}
      disabled={isSubmitting || isVerifying}
      onClick={() => void handleVerify()}
      aria-label={isVerifying ? "DNS verification in progress" : "Verify DNS records"}
    >
      <RefreshCw
        className={cn("h-4 w-4", isVerifying && "animate-spin")}
        aria-hidden
      />
      {isVerifying ? "Verifying…" : "Verify DNS"}
    </Button>
  );
}
