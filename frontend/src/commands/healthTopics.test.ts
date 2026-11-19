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
  ])("finds a health topic in %s", (text, phrase) => {
    expect(findHealthTopic(text)).toBe(phrase);
  });

  it.each([
    "What's on my calendar this week?",
    "How are the model weights loading in the tokenizer project?",
    "Draft the body of an email to my landlord",
    "How has my mood been?",
    "What's the status of my UCL application?",
  ])("finds nothing in %s", (text) => {
    expect(findHealthTopic(text)).toBeNull();
  });

  it("returns the earliest phrase when several appear", () => {
    expect(findHealthTopic("Compare my sleep with my steps")).toBe("sleep");
  });
});
