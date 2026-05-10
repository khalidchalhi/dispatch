import { NextResponse } from "next/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { getServerEnv, publicEnv } from "@/lib/env";

type RouteContext = {
  params: Promise<{ id: string }>;
};

type ThrottleBody = {
  rateLimit?: number;
};

export async function POST(request: Request, context: RouteContext) {
  const { id } = await context.params;
  const body = (await request.json().catch(() => ({}))) as ThrottleBody;
  const rateLimit = Number(body.rateLimit);

  if (!Number.isFinite(rateLimit) || rateLimit <= 0) {
    return NextResponse.json(
      {
        error: {
          code: "validation_error",
          message: "rateLimit must be a positive number.",
        },
      },
      { status: 400 },
    );
  }

  const requestIdHeader = getServerEnv().DISPATCH_WEB_REQUEST_ID_HEADER;
  const requestId =
    request.headers.get(requestIdHeader) ?? request.headers.get("x-request-id");

  const upstreamHeaders = new Headers({
    Accept: "application/json",
    "Content-Type": "application/json",
  });

  if (requestId) {
    upstreamHeaders.set(requestIdHeader, requestId);
  }

  const cookieHeader = request.headers.get("cookie");
  if (cookieHeader) {
    upstreamHeaders.set("cookie", cookieHeader);
  }

  const upstreamUrl = new URL(
    ENDPOINTS.domains.throttle(id),
    publicEnv.NEXT_PUBLIC_API_BASE_URL,
  );

  const upstreamResponse = await fetch(upstreamUrl, {
    method: "POST",
    headers: upstreamHeaders,
    body: JSON.stringify({
      rate_limit_per_hour: Math.trunc(rateLimit),
    }),
    cache: "no-store",
  }).catch(() => null);

  if (!upstreamResponse) {
    return NextResponse.json(
      {
        error: {
          code: "upstream_unavailable",
          message: "Unable to reach backend throttle service.",
        },
      },
      { status: 502 },
    );
  }

  const contentType = upstreamResponse.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await upstreamResponse.json().catch(() => ({}))
    : await upstreamResponse.text();

  return NextResponse.json(payload, { status: upstreamResponse.status });
}
