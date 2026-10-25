import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchDomains, resetApiTokenForTests } from "./api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("API session token", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    resetApiTokenForTests();
  });

  it("fetches the token once and sends it as a header, never in the URL", async () => {
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
      if (url.endsWith("/api/session")) return jsonResponse(200, { token: "tok-1" });
      return jsonResponse(200, []);
    });
    vi.stubGlobal("fetch", fetchMock);

    await fetchDomains();
    await fetchDomains();

    const sessionCalls = fetchMock.mock.calls.filter(([url]) => url.endsWith("/api/session"));
    expect(sessionCalls).toHaveLength(1);
    const apiCalls = fetchMock.mock.calls.filter(([url]) => url.endsWith("/api/domains"));
    expect(apiCalls).toHaveLength(2);
    for (const [url, init] of apiCalls) {
      expect(url).not.toContain("tok-1");
      expect(new Headers(init?.headers).get("X-Jarvis-Token")).toBe("tok-1");
    }
  });

  it("refetches the token and retries once after a 401 (backend restarted)", async () => {
    let token = "old";
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/api/session")) return jsonResponse(200, { token });
      const sent = new Headers(init?.headers).get("X-Jarvis-Token");
      return sent === "new" ? jsonResponse(200, []) : jsonResponse(401, { detail: "Missing or invalid Jarvis API token." });
    });
    vi.stubGlobal("fetch", fetchMock);

    await fetchDomains().catch(() => undefined);
    token = "new";
    await expect(fetchDomains()).resolves.toEqual([]);
  });
});
