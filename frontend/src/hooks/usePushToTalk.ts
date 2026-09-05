import { useCallback, useRef, useState } from "react";

export type RecorderStatus = "idle" | "recording" | "error";

interface UsePushToTalkOptions {
  onRecordingComplete: (blob: Blob) => void;
  onError: (message: string) => void;
}

/** Mechanics of a single hold-to-record gesture via MediaRecorder. Does not
 * know about transcription, turns, or playback — callers own what happens
 * to the recorded blob.
 *
 * getUserMedia's permission prompt can take an arbitrary amount of time to
 * resolve. If the user releases (stop) or cancels (Escape) before it
 * resolves, that release must still be honored once permission comes back
 * — otherwise a quick tap-and-release, or an Escape pressed while the
 * prompt is up, would be silently ignored and leave the caller's UI stuck
 * showing "listening" forever with the recorder never actually starting or
 * stopping. `pendingReleaseRef` records that intent across the await. */
export function usePushToTalk({ onRecordingComplete, onError }: UsePushToTalkOptions) {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  // The exact MediaStream already acquired below via getUserMedia — exposed
  // so a caller (the audio-reactive waveform) can attach a Web Audio
  // AnalyserNode to it directly, never requesting microphone permission a
  // second time.
  const [stream, setStream] = useState<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const cancelledRef = useRef(false);
  const pendingReleaseRef = useRef<"stop" | "cancel" | null>(null);
  const requestInFlightRef = useRef(false);

  const start = useCallback(async () => {
    if (mediaRecorderRef.current || requestInFlightRef.current) return; // already recording/requesting
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setStatus("error");
      onError("Voice recording is not supported in this browser.");
      return;
    }

    cancelledRef.current = false;
    pendingReleaseRef.current = null;
    requestInFlightRef.current = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      requestInFlightRef.current = false;

      const releasedWhilePending = pendingReleaseRef.current;
      pendingReleaseRef.current = null;
      if (releasedWhilePending) {
        stream.getTracks().forEach((track) => track.stop());
        setStatus("idle");
        return;
      }

      streamRef.current = stream;
      setStream(stream);
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };

      recorder.onstop = () => {
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        setStream(null);
        const wasCancelled = cancelledRef.current;
        mediaRecorderRef.current = null;
        const recordedChunks = chunksRef.current;
        chunksRef.current = [];
        if (!wasCancelled && recordedChunks.length > 0) {
          onRecordingComplete(new Blob(recordedChunks, { type: recorder.mimeType || "audio/webm" }));
        }
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setStatus("recording");
    } catch (err) {
      requestInFlightRef.current = false;
      pendingReleaseRef.current = null;
      setStatus("error");
      // Surface the real DOMException name/message (e.g. "NotAllowedError",
      // "NotFoundError", "NotReadableError", "SecurityError" for an
      // insecure-context rejection) rather than a generic message — the
      // specific cause is otherwise undiagnosable from the UI alone.
      const reason = err instanceof DOMException ? `${err.name}: ${err.message}` : String(err);
      onError(`Could not access the microphone (${reason}).`);
    }
  }, [onRecordingComplete, onError]);

  const stop = useCallback(() => {
    cancelledRef.current = false;
    if (requestInFlightRef.current) {
      pendingReleaseRef.current = "stop";
    }
    mediaRecorderRef.current?.stop();
    setStatus("idle");
  }, []);

  const cancel = useCallback(() => {
    cancelledRef.current = true;
    if (requestInFlightRef.current) {
      pendingReleaseRef.current = "cancel";
    }
    mediaRecorderRef.current?.stop();
    setStatus("idle");
  }, []);

  return { status, stream, start, stop, cancel };
}
