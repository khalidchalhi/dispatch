import { isInternalApiRoute } from "@/lib/api/endpoints";
import { toApiError, UnauthorizedError } from "@/lib/api/errors";
import { getMockApiJson } from "@/lib/api/mock-api";
import { redirectToLoginInBrowser } from "@/lib/auth/redirects";
import { publicEnv } from "@/lib/env";

type QueryValue = string | number | boolean | null | undefined;
type RequestBody = BodyInit | Record<string, unknown> | null | undefined;

export type ClientApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: RequestBody;
  query?: Record<string, QueryValue>;
  redirectOnUnauthorized?: boolean;
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

function resolveUrl(path: string) {
  if (/^https?:\/\//.test(path)) {
    return new URL(path);
  }

  if (isInternalApiRoute(path)) {
    return appendQuery(new URL(path, window.location.origin), undefined);
  }

  return new URL(path, publicEnv.NEXT_PUBLIC_API_BASE_URL);
}

function allowsLocalMockFallback(url: URL) {
  const currentHost = window.location.hostname;
  const apiHost = url.hostname;

  return (
    currentHost === "localhost" ||
    currentHost === "127.0.0.1" ||
    apiHost === "localhost" ||
    apiHost === "127.0.0.1"
  );
}

async function parseResponse<T>(
  response: Response,
  method: string,
  path: string,
  requestId: string,
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
      requestId,
      retryAfterSeconds:
        Number.isNaN(retryAfterSeconds ?? Number.NaN) ? null : retryAfterSeconds,
    });
  }

  return payload as T;
}

export async function clientJson<T>(
  path: string,
  init: ClientApiRequestOptions = {},
) {
  const method = init.method ?? "GET";
  const requestId = createRequestId();
  const requestHeaders = new Headers(init.headers);

  requestHeaders.set("Accept", "application/json");
  requestHeaders.set("x-request-id", requestId);

  const resolvedUrl = appendQuery(resolveUrl(path), init.query);
  let response: Response;

  try {
    response = await fetch(resolvedUrl, {
      ...init,
      body: resolveRequestBody(init.body, requestHeaders),
      credentials: "include",
      headers: requestHeaders,
    });
  } catch (error) {
    if (!isInternalApiRoute(path) && allowsLocalMockFallback(resolvedUrl)) {
      const fallback = getMockApiJson(resolvedUrl, init.query);
      if (fallback !== undefined) {
        return fallback as T;
      }
    }

    throw error;
  }

  try {
    return await parseResponse<T>(response, method, path, requestId);
  } catch (error) {
    if (
      error instanceof UnauthorizedError &&
      init.redirectOnUnauthorized !== false &&
      typeof window !== "undefined"
    ) {
      redirectToLoginInBrowser();
    }

    throw error;
  }
}
