import { describe, expect, it } from "vitest";
import { findCalendarTopic } from "./calendarTopics";

describe("findCalendarTopic", () => {
  it.each([
    ["What's on my calendar this week?", "what's on"],
    ["What's my schedule tomorrow?", "schedule"],
    ["Are there any meetings today?", "meetings"],
    ["Am I free on Saturday afternoon?", "am i free"],
    ["When is my next appointment?", "when is my"],
    ["Anything coming up this weekend?", "coming up"],
    ["What are my plans for tonight?", "my plans"],
    ["What do I have on Wednesday?", "what do i have"],
    ["Show me my events for next week", "my events"],
  ])("finds a calendar topic in %s", (text, phrase) => {
    expect(findCalendarTopic(text)).toBe(phrase);
  });

  it.each([
    "How did I sleep last night?",
    "How does the event loop work in the backend?",
    "Run the tests for the tokenizer project",
    "Don't check my calendar, just give me a focus tip",
    "Answer without looking at my schedule",
    "What should I focus on?",
  ])("finds nothing in %s", (text) => {
    expect(findCalendarTopic(text)).toBeNull();
  });
});
