import { describe, expect, it } from "vitest";
import { resolveApiBaseUrl } from "./api";

function loc(href: string): Pick<Location, "protocol" | "origin"> {
  const url = new URL(href);
  return { protocol: url.protocol, origin: url.origin };
}

describe("resolveApiBaseUrl", () => {
  it("uses the page's own origin in a production build served by the backend", () => {
    expect(
      resolveApiBaseUrl({ envOverride: undefined, isDev: false, location: loc("http://127.0.0.1:8013/") }),
    ).toBe("http://127.0.0.1:8013");
  });

  it("keeps the default port when the backend serves the page on 8000", () => {
    expect(
      resolveApiBaseUrl({ envOverride: undefined, isDev: false, location: loc("http://127.0.0.1:8000/index.html") }),
    ).toBe("http://127.0.0.1:8000");
  });

  it("points the Vite dev server (its own port) at the default backend", () => {
    expect(
      resolveApiBaseUrl({ envOverride: undefined, isDev: true, location: loc("http://127.0.0.1:5173/") }),
    ).toBe("http://127.0.0.1:8000");
  });

  it("lets an explicit VITE_API_BASE_URL win in both modes, without a trailing slash", () => {
    for (const isDev of [true, false]) {
      expect(
        resolveApiBaseUrl({ envOverride: "http://127.0.0.1:9100/", isDev, location: loc("http://127.0.0.1:8013/") }),
      ).toBe("http://127.0.0.1:9100");
    }
  });

  it("ignores an empty override", () => {
    expect(
      resolveApiBaseUrl({ envOverride: "  ", isDev: false, location: loc("http://127.0.0.1:8013/") }),
    ).toBe("http://127.0.0.1:8013");
  });

  it("falls back to the default backend when the page is not served over http", () => {
    expect(
      resolveApiBaseUrl({ envOverride: undefined, isDev: false, location: loc("tauri://localhost/offline.html") }),
    ).toBe("http://127.0.0.1:8000");
    expect(resolveApiBaseUrl({ envOverride: undefined, isDev: false, location: undefined })).toBe(
      "http://127.0.0.1:8000",
    );
  });
});
