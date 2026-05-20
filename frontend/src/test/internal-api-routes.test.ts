import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST as resetBreaker } from "@/app/api/circuit-breakers/[id]/reset/route";
import { POST as updateThrottle } from "@/app/api/domains/[id]/throttle/route";

describe("internal API route proxies", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("window", undefined);
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("proxies domain throttle updates to the backend", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ rate_limit_per_hour: 750 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await updateThrottle(
      new Request("http://localhost:3000/api/domains/dom-1/throttle", {
        method: "POST",
        headers: {
          cookie: "dispatch_web_session=session-value",
          "x-request-id": "req-throttle",
        },
        body: JSON.stringify({ rateLimit: 750 }),
      }),
      { params: Promise.resolve({ id: "dom-1" }) },
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ rate_limit_per_hour: 750 });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(String(url)).toBe("http://localhost:8000/domains/dom-1/throttle");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ rate_limit_per_hour: 750 }));

    const headers = init.headers as Headers;
    expect(headers.get("cookie")).toBe("dispatch_web_session=session-value");
    expect(headers.get("x-request-id")).toBe("req-throttle");
  });

  it("rejects invalid throttle payloads before proxying", async () => {
    const response = await updateThrottle(
      new Request("http://localhost:3000/api/domains/dom-1/throttle", {
        method: "POST",
        body: JSON.stringify({ rateLimit: 0 }),
      }),
      { params: Promise.resolve({ id: "dom-1" }) },
    );

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("proxies circuit breaker reset requests to the backend", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ message: "Circuit breaker reset" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await resetBreaker(
      new Request("http://localhost:3000/api/circuit-breakers/domain:dom-1/reset", {
        method: "POST",
        headers: {
          cookie: "dispatch_web_session=session-value",
          "x-request-id": "req-reset",
        },
        body: JSON.stringify({
          justification: "Runbook reviewed and reputation recovered.",
        }),
      }),
      { params: Promise.resolve({ id: "domain:dom-1" }) },
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      message: "Circuit breaker reset",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(String(url)).toBe(
      "http://localhost:8000/circuit-breakers/domain:dom-1/reset",
    );
    expect(init.method).toBe("POST");
    expect(init.body).toBe(
      JSON.stringify({
        justification: "Runbook reviewed and reputation recovered.",
      }),
    );
  });
});
