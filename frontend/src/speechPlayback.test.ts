import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { playSpeech, splitSpeechChunks } from "./speechPlayback";

describe("splitSpeechChunks", () => {
  it("keeps a single sentence whole", () => {
    expect(splitSpeechChunks("It's healing well.")).toEqual(["It's healing well."]);
  });

  it("makes a short first chunk and merges later sentences", () => {
    const text =
      "Your knee looks stable this week. You logged three sessions. The longest was forty minutes. " +
      "Swelling was lower than last week. Keep the same plan until Friday.";
    const chunks = splitSpeechChunks(text);
    expect(chunks[0]).toBe("Your knee looks stable this week.");
    expect(chunks.length).toBe(2);
    expect(chunks.join(" ")).toBe(text);
  });

  it("does not split decimals, and splits on line breaks", () => {
    expect(splitSpeechChunks("The model took 3.5 seconds to answer you.\nNext line here.")).toEqual([
      "The model took 3.5 seconds to answer you.",
      "Next line here.",
    ]);
  });

  it("splits after closing quotes and keeps every word", () => {
    const text = 'He said "it works perfectly fine." Then we moved on to the next item. ' + "x".repeat(130);
    const chunks = splitSpeechChunks(text);
    expect(chunks[0]).toBe('He said "it works perfectly fine."');
    expect(chunks.join(" ")).toBe(text);
  });

  it("returns nothing for blank text", () => {
    expect(splitSpeechChunks("  \n  ")).toEqual([]);
  });
});

describe("playSpeech", () => {
  let audio: HTMLAudioElement;
  let synth: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    audio = document.createElement("audio");
    vi.spyOn(audio, "play").mockResolvedValue(undefined);
    vi.spyOn(audio, "pause").mockImplementation(() => {});
    URL.createObjectURL = vi.fn((blob: Blob) => `blob:${(blob as Blob & { label?: string }).label ?? "x"}`);
    URL.revokeObjectURL = vi.fn();
    synth = vi.spyOn(api, "synthesizeSpeech").mockImplementation(async (text: string) => {
      const blob = new Blob([text], { type: "audio/mpeg" }) as Blob & { label?: string };
      blob.label = text.slice(0, 8);
      return blob;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const text =
    "First sentence is right here. " +
    "Second sentence is long enough to be merged with the third one later on. " +
    "Third sentence finishes the second chunk off nicely and makes it long enough. " +
    "Fourth sentence makes the third chunk.";

  it("starts after the first chunk and plays every chunk in order on one element", async () => {
    const chunks = splitSpeechChunks(text);
    expect(chunks.length).toBe(3);
    const speech = playSpeech(text, audio);
    await speech.started;
    expect(audio.play).toHaveBeenCalledTimes(1);
    // The next chunks were requested before the first finished playing.
    expect(synth).toHaveBeenCalledTimes(3);
    for (let i = 1; i < chunks.length; i += 1) {
      audio.dispatchEvent(new Event("ended"));
      await vi.waitFor(() => expect(audio.play).toHaveBeenCalledTimes(i + 1));
    }
    audio.dispatchEvent(new Event("ended"));
    await speech.done;
    expect(synth.mock.calls.map((call) => call[0])).toEqual(chunks);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(3);
  });

  it("stop() ends playback and skips the remaining chunks", async () => {
    const speech = playSpeech(text, audio);
    await speech.started;
    speech.stop();
    await speech.done;
    expect(audio.pause).toHaveBeenCalled();
    expect(audio.play).toHaveBeenCalledTimes(1);
  });

  it("rejects started when the first chunk fails", async () => {
    synth.mockRejectedValueOnce(new Error("502"));
    const speech = playSpeech(text, audio);
    await expect(speech.started).rejects.toThrow("502");
    await expect(speech.done).rejects.toThrow("502");
    expect(audio.play).not.toHaveBeenCalled();
  });

  it("rejects done when a later chunk fails after playback started", async () => {
    synth
      .mockImplementationOnce(async () => new Blob(["a"]))
      .mockImplementationOnce(async () => {
        throw new Error("second failed");
      });
    const speech = playSpeech(text, audio);
    await speech.started;
    audio.dispatchEvent(new Event("ended"));
    await expect(speech.done).rejects.toThrow("second failed");
  });
});
