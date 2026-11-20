import { describe, expect, it } from "vitest";
import { findHealthTopic } from "./healthTopics";

describe("findHealthTopic", () => {
  it.each([
    ["What Google Health data can you see?", "google health"],
    ["sync from Fitbit again", "fitbit"],
    ["How many steps did I do yesterday?", "steps"],
    ["Did I sleep well?", "sleep"],
    ["what's my HRV", "hrv"],
    ["What's my weight trend?", "my weight"],
    ["How much did I weigh last month?", "weigh"],
    ["Show me my recent workouts", "workouts"],
    ["How is my knee doing?", "knee"],
    // Wordings that missed BODY in real use (D120).
    ["Should I train today or take a rest day?", "should i train"],
    ["How am I doing physically this week?", "physically"],
    ["How far did I run on my last run?", "how far did i"],
    ["Did I walk enough today?", "did i walk"],
    ["When was my last gym session?", "last gym session"],
    ["I want to work out today, what should I do?", "work out"],
    ["How's my fitness trending?", "my fitness"],
    ["I didn't sleep well, any advice?", "sleep"],
  ])("finds a health topic in %s", (text, phrase) => {
    expect(findHealthTopic(text)).toBe(phrase);
  });

  it.each([
    "What's on my calendar this week?",
    "How are the model weights loading in the tokenizer project?",
    "Draft the body of an email to my landlord",
    "How has my mood been?",
    "What's the status of my UCL application?",
    "Run the tests for the tokenizer project",
    "Walk me through the export flow",
    "Help me work out the budget for next month",
    "Is the backup job running?",
    "Don't look at my health data, just give me a focus tip",
    "Answer without using my sleep data",
  ])("finds nothing in %s", (text) => {
    expect(findHealthTopic(text)).toBeNull();
  });

  it("returns the earliest phrase when several appear", () => {
    expect(findHealthTopic("Compare my sleep with my steps")).toBe("sleep");
  });
});
