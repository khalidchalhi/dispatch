"use client";

import { useEffect, useRef, useState } from "react";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import type { SegmentDsl } from "@/types/segment";
import type { ApiSegmentEvaluateResponse } from "../_lib/segments-api";

const DEBOUNCE_MS = 600;

type PreviewPanelProps = {
  segmentId: string | null;
  dsl: SegmentDsl;
  isValid: boolean;
};

export function PreviewPanel({ segmentId, dsl, isValid }: PreviewPanelProps) {
  const [preview, setPreview] = useState<ApiSegmentEvaluateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!isValid || !segmentId) return;

    const timer = setTimeout(async () => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setLoading(true);
      setError(false);
      try {
        const result = await clientJson<ApiSegmentEvaluateResponse>(
          apiEndpoints.segments.evaluate(segmentId),
          {
            method: "POST",
            signal: controller.signal,
          },
        );
        if (!controller.signal.aborted) {
          setPreview(result);
        }
      } catch {
        if (!controller.signal.aborted) {
          setError(true);
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      abortRef.current?.abort();
    };
  }, [segmentId, dsl, isValid]);

  if (!isValid) {
    return (
      <div className="surface-panel p-6">
        <h2 className="section-title mb-3">Preview</h2>
        <p className="text-sm text-text-muted">
          Fix validation errors to see the audience preview.
        </p>
      </div>
    );
  }

  if (!segmentId) {
    return (
      <div className="surface-panel p-6">
        <h2 className="section-title mb-3">Preview</h2>
        <p className="text-sm text-text-muted">
          Save the segment first to enable live preview.
        </p>
      </div>
    );
  }

  return (
    <div className="surface-panel p-6 grid gap-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="section-title">Preview</h2>
        {loading ? (
          <span className="text-xs text-text-muted" role="status" aria-live="polite">
            Loading…
          </span>
        ) : null}
      </div>

      {error ? (
        <p className="text-sm text-danger" role="alert">
          Preview failed. Check your connection and try again.
        </p>
      ) : null}

      {preview ? (
        <>
          <div className="surface-panel-muted rounded-lg p-4 text-center">
            <p className="text-3xl font-bold tabular-nums">
              {preview.total_count.toLocaleString()}
            </p>
            <p className="mt-1 text-sm text-text-muted">
              contacts match this segment
            </p>
          </div>

          {preview.sample.length > 0 ? (
            <div>
              <h3 className="text-xs font-medium text-text-muted uppercase tracking-wide mb-2">
                Sample contacts ({preview.sample.length})
              </h3>
              <ul role="list" className="divide-y divide-border rounded-lg border border-border overflow-hidden">
                {preview.sample.map((contact) => (
                  <li
                    key={contact.id}
                    className="flex items-center justify-between gap-3 px-4 py-2"
                  >
                    <span className="text-sm font-medium truncate">
                      {contact.email}
                    </span>
                    <span className="text-xs text-text-muted shrink-0">
                      {contact.lifecycle_status}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}

      {!preview && !loading && !error ? (
        <p className="text-sm text-text-muted">
          Modify the segment to refresh the preview.
        </p>
      ) : null}
    </div>
  );
}

