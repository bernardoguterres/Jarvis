import { useCallback, useEffect, useRef, useState } from "react";
import { transcribeAudio, synthesizeSpeech, type Message } from "../api";
import { usePushToTalk } from "./usePushToTalk";
import { parseCommand, type ParsedCommand } from "../commands/registry";
import type { VoiceState } from "../voiceState";

export type VoiceDisplayState = VoiceState | "cancelled";

export interface VoiceCaptureController {
  voiceState: VoiceDisplayState;
  voiceError: string | null;
  lastCommand: { heard: string; interpreted: string; sensitive: boolean } | null;
  pushToTalkStatus: "idle" | "recording" | "error";
  micStream: MediaStream | null;
  ttsAudioEl: HTMLAudioElement | null;
  start: () => void;
  stop: () => void;
  cancel: () => void;
}

interface UseVoiceCaptureOptions {
  /** Checked once a recording has genuinely completed, before transcription
   * even starts — mirrors the exact gate DomainView/GeneralConversation
   * already had: `false` aborts silently (e.g. no conversation selected
   * yet), a string aborts with that message as a real voice error, `true`
   * proceeds. Omit to always proceed. */
  guard?: () => true | false | string;
  /** Any recognized actionable command — navigate, focus_control (shows,
   * never activates), safe_action (the caller executes it immediately —
   * e.g. a read-only sync), or confirm_required (the caller owns showing
   * the confirmation UI and calling the real action only if accepted; this
   * hook never executes one of these directly). The same handler App.tsx
   * already wires for the Command Palette and every conversation surface,
   * so a command behaves identically whether typed or spoken, from
   * anywhere. */
  onSystemCommand?: (
    parsed: Extract<ParsedCommand, { kind: "navigate" } | { kind: "focus_control" } | { kind: "safe_action" } | { kind: "confirm_required" }>,
  ) => void;
  /** Anything that isn't a command or confirmation-required action: an
   * ordinary question, sent exactly as domain/general conversations
   * already do. */
  submitTurn: (transcript: string) => Promise<{ ok: boolean; assistantMessage: Message | null }>;
}

/** The one push-to-talk voice state machine, shared by every surface
 * (DomainView, GeneralConversation, and the ambient Home/Centre capture in
 * App.tsx) so there is never more than one microphone session, one
 * AudioContext graph, or one TTS playback path active at a time — each
 * caller only supplies what's specific to it (a start-guard and where a
 * non-command transcript should actually be sent). Every transcript goes
 * through the same deterministic hierarchy: a recognized command (safe,
 * focus-only, or confirmation-required) is handed to `onSystemCommand`
 * (never auto-executed here — the caller decides what each kind actually
 * does), a blocked/destructive phrase is refused with an explanation, and
 * anything else is sent as an ordinary question via `submitTurn` — never
 * silently dropped just because the caller is a Centre page rather than an
 * active conversation. */
export function useVoiceCapture({ guard, onSystemCommand, submitTurn }: UseVoiceCaptureOptions): VoiceCaptureController {
  const [voiceState, setVoiceState] = useState<VoiceDisplayState>("idle");
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [lastCommand, setLastCommand] = useState<{ heard: string; interpreted: string; sensitive: boolean } | null>(null);
  const audioPlaybackRef = useRef<HTMLAudioElement | null>(null);
  const [ttsAudioEl, setTtsAudioEl] = useState<HTMLAudioElement | null>(null);
  const cancelFlashRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleRecordingComplete = useCallback(
    (blob: Blob) => {
      if (guard) {
        const result = guard();
        if (result === false) return;
        if (typeof result === "string") {
          setVoiceState("error");
          setVoiceError(result);
          return;
        }
      }

      setVoiceState("transcribing");
      setVoiceError(null);

      (async () => {
        try {
          const transcript = await transcribeAudio(blob);
          if (!transcript.trim()) {
            setVoiceState("error");
            setVoiceError("Could not hear anything to transcribe.");
            return;
          }

          // Deterministic, model-independent routing — the same parser the
          // Command Palette uses (see commands/registry.ts). A safe command
          // executes immediately; a confirmation-required one only ever
          // reaches the caller's confirmation UI; a blocked phrase is
          // refused with an explanation; anything else is an ordinary
          // question and is sent as one, regardless of which surface this
          // is (never "not recognized as a command" just because there's
          // no active domain/general conversation here).
          const parsed = parseCommand(transcript);
          if (parsed.kind === "navigate" || parsed.kind === "focus_control" || parsed.kind === "safe_action" || parsed.kind === "confirm_required") {
            setLastCommand({
              heard: parsed.heard,
              interpreted:
                parsed.kind === "focus_control"
                  ? `${parsed.interpreted} — review and confirm it there yourself`
                  : parsed.kind === "confirm_required"
                    ? `${parsed.interpreted} — confirmation required`
                    : parsed.interpreted,
              sensitive: parsed.kind === "focus_control" || parsed.kind === "confirm_required",
            });
            onSystemCommand?.(parsed);
            setVoiceState("idle");
            return;
          }
          if (parsed.kind === "blocked") {
            setLastCommand({ heard: parsed.heard, interpreted: parsed.explanation, sensitive: true });
            setVoiceState("idle");
            return;
          }
          setLastCommand(null);

          setVoiceState("thinking");
          const { ok, assistantMessage } = await submitTurn(transcript);
          if (!ok || !assistantMessage) {
            setVoiceState("error");
            return;
          }

          const audioBlob = await synthesizeSpeech(assistantMessage.content);
          const audioUrl = URL.createObjectURL(audioBlob);
          const audioEl = audioPlaybackRef.current ?? new Audio();
          audioPlaybackRef.current = audioEl;
          audioEl.src = audioUrl;
          audioEl.onended = () => {
            URL.revokeObjectURL(audioUrl);
            setTtsAudioEl(null);
            setVoiceState("idle");
          };
          // setVoiceState("speaking") before .play() resolves (so the
          // overlay appears immediately); ttsAudioEl only *after* .play()
          // resolves — tapping a Web Audio analyser onto the element any
          // earlier is a real Chromium loading race (see D78).
          setVoiceState("speaking");
          await audioEl.play();
          setTtsAudioEl(audioEl);
        } catch {
          setTtsAudioEl(null);
          setVoiceState("error");
          setVoiceError("The voice round-trip failed.");
        }
      })();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [guard, submitTurn, onSystemCommand],
  );

  const handleVoiceError = useCallback((message: string) => {
    setVoiceState("error");
    setVoiceError(message);
  }, []);

  const pushToTalk = usePushToTalk({ onRecordingComplete: handleRecordingComplete, onError: handleVoiceError });
  const voiceBusy = voiceState !== "idle" && voiceState !== "error" && voiceState !== "cancelled";

  const start = useCallback(() => {
    if (voiceBusy) return;
    setVoiceError(null);
    setVoiceState("listening");
    pushToTalk.start();
  }, [voiceBusy, pushToTalk]);

  const stop = useCallback(() => {
    // Gate on our own voiceState, not the hook's internal status — a
    // release must be honored even while getUserMedia's permission prompt
    // is still pending (status hasn't reached "recording" yet). In that
    // case no MediaRecorder ever started, so onRecordingComplete never
    // fires to bring voiceState back to idle — reset it here instead. When
    // a recorder genuinely was running, pushToTalk.stop() synchronously
    // triggers handleRecordingComplete, which already sets "transcribing"
    // in the same batch — forcing "idle" here too would silently clobber
    // that (React batches same-tick setState calls; the last call wins).
    if (voiceState !== "listening") return;
    const wasRecording = pushToTalk.status === "recording";
    pushToTalk.stop();
    if (!wasRecording) setVoiceState("idle");
  }, [voiceState, pushToTalk]);

  const cancel = useCallback(() => {
    // An "error" state (e.g. a failed microphone permission check) has
    // nothing actually recording to cancel — dismiss it directly, rather
    // than requiring voiceState === "listening" below, which would leave
    // every Escape/cancel call from an error state silently doing nothing.
    if (voiceState === "error") {
      setVoiceError(null);
      setVoiceState("idle");
      return;
    }
    if (voiceState !== "listening") return;
    pushToTalk.cancel();
    if (cancelFlashRef.current) clearTimeout(cancelFlashRef.current);
    setVoiceState("cancelled");
    cancelFlashRef.current = setTimeout(() => setVoiceState("idle"), 500);
  }, [voiceState, pushToTalk]);

  useEffect(() => {
    return () => {
      if (cancelFlashRef.current) clearTimeout(cancelFlashRef.current);
    };
  }, []);

  return {
    voiceState,
    voiceError,
    lastCommand,
    pushToTalkStatus: pushToTalk.status,
    micStream: pushToTalk.stream,
    ttsAudioEl,
    start,
    stop,
    cancel,
  };
}
