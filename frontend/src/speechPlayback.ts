import { synthesizeSpeech } from "./api";

// Edge TTS returns its first audio in about 1 to 2 seconds but can take
// several more to finish a whole reply, and the old path waited for all of
// it before playing anything. Splitting the reply into sentences lets the
// first one play while the rest are still being synthesized.

/** The first chunk is kept short so playback starts quickly. */
const FIRST_CHUNK_MIN_CHARS = 20;
/** Later chunks are merged up to this size so a long reply does not turn
 * into dozens of separate requests. */
const LATER_CHUNK_MIN_CHARS = 120;
/** How many chunks are requested ahead of the one playing. */
const LOOKAHEAD = 2;

/** Splits text into speakable chunks at sentence ends and line breaks.
 * Joining the chunks with spaces gives back the original words in order;
 * nothing is dropped or rewritten. */
export function splitSpeechChunks(text: string): string[] {
  const sentences = text
    .split(/\n+/)
    .flatMap((line) => line.split(/(?<=[.!?…]["'”’)\]]*)\s+/))
    .map((part) => part.replace(/\s+/g, " ").trim())
    .filter((part) => part.length > 0);

  const chunks: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    current = current ? `${current} ${sentence}` : sentence;
    const min = chunks.length === 0 ? FIRST_CHUNK_MIN_CHARS : LATER_CHUNK_MIN_CHARS;
    if (current.length >= min) {
      chunks.push(current);
      current = "";
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

export interface SpeechPlayback {
  /** Resolves once the first chunk has started playing; rejects if it never
   * does (the first synthesis or play() failed). */
  started: Promise<void>;
  /** Resolves when every chunk has played or playback was stopped; rejects
   * if any chunk fails. */
  done: Promise<void>;
  /** Stops playback now and skips every remaining chunk. */
  stop: () => void;
}

/** Speaks `text` through `audioEl`, one chunk at a time, always on the same
 * element so a Web Audio analyser attached to it keeps working. */
export function playSpeech(text: string, audioEl: HTMLAudioElement): SpeechPlayback {
  const chunks = splitSpeechChunks(text);
  const requests: Promise<Blob>[] = [];
  let stopped = false;
  let currentUrl: string | null = null;
  let finishCurrent: (() => void) | null = null;

  let markStarted!: () => void;
  let failStart!: (error: unknown) => void;
  let hasStarted = false;
  const started = new Promise<void>((resolve, reject) => {
    markStarted = resolve;
    failStart = reject;
  });
  started.catch(() => {});

  function request(index: number): Promise<Blob> | undefined {
    if (index >= chunks.length) return undefined;
    if (!requests[index]) {
      requests[index] = synthesizeSpeech(chunks[index]);
      // A prefetched chunk can fail before its turn; its error is reported
      // when that chunk is awaited, never as an unhandled rejection.
      requests[index].catch(() => {});
    }
    return requests[index];
  }

  function releaseUrl() {
    if (currentUrl) {
      URL.revokeObjectURL(currentUrl);
      currentUrl = null;
    }
  }

  function playToEnd(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const cleanup = () => {
        audioEl.removeEventListener("ended", onEnded);
        audioEl.removeEventListener("error", onError);
        finishCurrent = null;
      };
      const onEnded = () => {
        cleanup();
        resolve();
      };
      const onError = () => {
        cleanup();
        reject(new Error("Audio playback failed"));
      };
      audioEl.addEventListener("ended", onEnded);
      audioEl.addEventListener("error", onError);
      finishCurrent = onEnded;
      audioEl.play().then(
        () => {
          if (!hasStarted) {
            hasStarted = true;
            markStarted();
          }
        },
        (error: unknown) => {
          cleanup();
          reject(error);
        },
      );
    });
  }

  async function run() {
    if (chunks.length === 0) throw new Error("Nothing to speak");
    for (let index = 0; index < chunks.length; index += 1) {
      for (let ahead = index; ahead <= index + LOOKAHEAD; ahead += 1) request(ahead);
      const blob = await requests[index];
      if (stopped) return;
      releaseUrl();
      currentUrl = URL.createObjectURL(blob);
      audioEl.src = currentUrl;
      await playToEnd();
      if (stopped) return;
    }
  }

  const done = run().then(
    () => {
      releaseUrl();
      if (!hasStarted) {
        hasStarted = true;
        markStarted();
      }
    },
    (error: unknown) => {
      releaseUrl();
      if (!hasStarted) failStart(error);
      throw error;
    },
  );
  done.catch(() => {});

  return {
    started,
    done,
    stop() {
      if (stopped) return;
      stopped = true;
      audioEl.pause();
      audioEl.currentTime = 0;
      finishCurrent?.();
      releaseUrl();
    },
  };
}
