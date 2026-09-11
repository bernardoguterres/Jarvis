import { describe, expect, it } from "vitest";
import { decodeHtmlEntities } from "./decodeEntities";

describe("decodeHtmlEntities", () => {
  it("decodes an apostrophe entity", () => {
    expect(decodeHtmlEntities("What&#x27;s left before the release?")).toBe("What's left before the release?");
    expect(decodeHtmlEntities("What&#39;s left")).toBe("What's left");
    expect(decodeHtmlEntities("What&apos;s left")).toBe("What's left");
  });

  it("decodes an ampersand entity", () => {
    expect(decodeHtmlEntities("Q&amp;A session")).toBe("Q&A session");
  });

  it("decodes less-than/greater-than entities", () => {
    expect(decodeHtmlEntities("5 &lt; 10 &gt; 2")).toBe("5 < 10 > 2");
  });

  it("decodes text that resembles an HTML tag without ever executing as markup", () => {
    // Regression for the actual bug: a server-escaped snippet like
    // "&lt;script&gt;" must come back as the literal, inert text
    // "<script>" — this function only ever turns entities back into
    // characters for a plain React text child, never for
    // dangerouslySetInnerHTML, so the result can never be parsed as markup.
    expect(decodeHtmlEntities("&lt;script&gt;alert(1)&lt;/script&gt;")).toBe("<script>alert(1)</script>");
  });

  it("leaves already-decoded text unchanged", () => {
    expect(decodeHtmlEntities("What's left before the release?")).toBe("What's left before the release?");
    expect(decodeHtmlEntities("Q&A session")).toBe("Q&A session");
  });

  it("does not mangle a bare ampersand that isn't part of a known entity", () => {
    expect(decodeHtmlEntities("Terms & Conditions")).toBe("Terms & Conditions");
  });

  it("is idempotent — decoding an already-decoded string is a no-op", () => {
    const once = decodeHtmlEntities("What&#x27;s left?");
    const twice = decodeHtmlEntities(once);
    expect(twice).toBe(once);
  });

  it("passes through empty/falsy input unchanged", () => {
    expect(decodeHtmlEntities("")).toBe("");
  });
});
