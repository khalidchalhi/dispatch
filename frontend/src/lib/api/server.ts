import "server-only";
import { cookies, headers } from "next/headers";
import { getServerEnv, publicEnv } from "@/lib/env";
import { isInternalApiRoute } from "@/lib/api/endpoints";
import { toApiError } from "@/lib/api/errors";
import { getMockApiJson } from "@/lib/api/mock-api";

type QueryValue = string | number | boolean | null | undefined;
type RequestBody = BodyInit | Record<string, unknown> | null | undefined;

export type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: RequestBody;
  query?: Record<string, QueryValue>;
};

function createRequestId() {
  return crypto.randomUUID();
}

function isBodyInit(value: RequestBody): value is BodyInit {
  return (
    typeof value === "string" ||
    value instanceof Blob ||
    value instanceof FormData ||
    value instanceof URLSearchParams ||
    value instanceof ArrayBuffer ||
    ArrayBuffer.isView(value)
  );
}

function resolveRequestBody(body: RequestBody, requestHeaders: Headers) {
  if (body === undefined || body === null) {
    return undefined;
  }

  if (isBodyInit(body)) {
    return body;
  }

  requestHeaders.set("Content-Type", "application/json");
  return JSON.stringify(body);
}

function appendQuery(url: URL, query?: Record<string, QueryValue>) {
  if (!query) {
    return url;
  }

  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }

    url.searchParams.set(key, String(value));
  }

  return url;
}

async function resolveUrl(path: string) {
  if (/^https?:\/\//.test(path)) {
    return appendQuery(new URL(path), undefined);
  }

  if (isInternalApiRoute(path)) {
    return new URL(path, getServerEnv().DISPATCH_WEB_APP_ORIGIN);
  }

  return new URL(path, publicEnv.NEXT_PUBLIC_API_BASE_URL);
}

async function parseResponse<T>(
  response: Response,
  method: string,
  path: string,
  fallbackRequestId: string,
) {
  const contentType = response.headers.get("content-type");
  const retryAfterHeader = response.headers.get("retry-after");
  const retryAfterSeconds = retryAfterHeader
    ? Number.parseInt(retryAfterHeader, 10)
    : null;
  const payload =
    contentType?.includes("application/json")
      ? await response.json()
      : await response.text();

  if (!response.ok) {
    throw toApiError(response.status, payload, {
      method,
      path,
      requestId:
        response.headers.get(getServerEnv().DISPATCH_WEB_REQUEST_ID_HEADER) ??
        fallbackRequestId,
      retryAfterSeconds:
        Number.isNaN(retryAfterSeconds ?? Number.NaN) ? null : retryAfterSeconds,
    });
  }

  return payload as T;
}

export async function serverJson<T>(path: string, init: ApiRequestOptions = {}) {
  const serverEnv = getServerEnv();
  const headerStore = await headers();
  const cookieStore = await cookies();
  const method = init.method ?? "GET";
  const requestId =
    headerStore.get(serverEnv.DISPATCH_WEB_REQUEST_ID_HEADER) ?? createRequestId();
  const resolvedUrl = appendQuery(await resolveUrl(path), init.query);
  const requestHeaders = new Headers(init.headers);

  requestHeaders.set("Accept", "application/json");
  requestHeaders.set(serverEnv.DISPATCH_WEB_REQUEST_ID_HEADER, requestId);

  const forwardedCookies = cookieStore.toString();

  if (forwardedCookies) {
    requestHeaders.set("cookie", forwardedCookies);
  }

  let response: Response;
  try {
    response = await fetch(resolvedUrl, {
      ...init,
      body: resolveRequestBody(init.body, requestHeaders),
      cache: init.cache ?? "no-store",
      headers: requestHeaders,
    });
  } catch (error) {
    if (serverEnv.DISPATCH_WEB_ENABLE_DEV_SESSION) {
      const fallback = getMockApiJson(resolvedUrl, init.query);
      if (fallback !== undefined) {
        return fallback as T;
      }
    }

    throw error;
  }

  return parseResponse<T>(response, method, path, requestId);
}
