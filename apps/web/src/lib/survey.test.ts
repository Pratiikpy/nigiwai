import { describe, expect, it } from "vitest";
import type { PickerItem } from "./api";
import { districtProblem, initials, metaLine, parseAreas, parseConsent, pickProgress } from "./survey";

describe("initials", () => {
  it("takes two letters and drops a leading article", () => {
    expect(initials("The Lantern Hollow")).toBe("LH");
    expect(initials("Radiohead")).toBe("R");
    expect(initials("Björk")).toBe("B");
    expect(initials("Simon & Garfunkel")).toBe("SG");
  });
  it("copes with names that are only symbols or non-Latin script", () => {
    expect(initials("!!!")).toBe("?");
    expect(initials("渋谷 系")).toBe("渋系");
    expect(initials("")).toBe("?");
  });
});

describe("metaLine", () => {
  const base: PickerItem = {
    entity_id: "x",
    name: "N",
    type: "movie",
    year: 2019,
    description: null,
    disambiguation: null,
  };
  it("joins what is known", () => {
    expect(metaLine(base)).toBe("Film · 2019");
    expect(metaLine({ ...base, year: null })).toBe("Film");
  });
});

describe("pickProgress", () => {
  it("counts down to the minimum, then allows continuing", () => {
    expect(pickProgress(0, 3, 5)).toEqual({ text: "Pick at least 3 to continue.", canContinue: false });
    expect(pickProgress(2, 3, 5)).toEqual({ text: "Pick 1 more to continue.", canContinue: false });
    expect(pickProgress(3, 3, 5).canContinue).toBe(true);
    expect(pickProgress(5, 3, 5).text).toBe("All 5 in. Nice.");
  });
});

describe("parseConsent", () => {
  it("splits paragraphs and bold lead-ins into data, never HTML", () => {
    const out = parseConsent("**What we collect.** Picks <b>only</b>.\n\n**Who sees it.** Groups.\n\nPlain.");
    expect(out).toHaveLength(3);
    expect(out[0]).toEqual([
      { text: "What we collect.", strong: true },
      { text: " Picks <b>only</b>.", strong: false },
    ]);
    expect(out[2]).toEqual([{ text: "Plain.", strong: false }]);
  });
  it("handles empty input", () => {
    expect(parseConsent("")).toEqual([]);
    expect(parseConsent("\n\n  \n")).toEqual([]);
  });
});

describe("districtProblem", () => {
  it("accepts place names and refuses contact details", () => {
    expect(districtProblem("")).toBeNull();
    expect(districtProblem("Eastside")).toBeNull();
    expect(districtProblem("me@example.com")).not.toBeNull();
    expect(districtProblem("https://x.test")).not.toBeNull();
    expect(districtProblem("12345")).not.toBeNull();
    expect(districtProblem("x".repeat(61))).not.toBeNull();
  });
});

describe("parseAreas", () => {
  it("reads a comma-separated line into clean, distinct names", () => {
    expect(parseAreas("")).toEqual({ areas: [], problem: null });
    expect(parseAreas("Eastside, Old Town ,  Riverside\nHarbour; ")).toEqual({ areas: ["Eastside", "Old Town", "Riverside", "Harbour"], problem: null });
    expect(parseAreas("Old   Town").areas).toEqual(["Old Town"]);
  });
  it("refuses a repeat (by spelling and by accents), contact details, a long name and more than twelve", () => {
    expect(parseAreas("Eastside, eastside").problem).toContain("twice");
    expect(parseAreas("Café, Cafe").problem).toContain("twice");
    expect(parseAreas("Eastside, me@example.com").problem).not.toBeNull();
    expect(parseAreas("x".repeat(41)).problem).toContain("longer than 40");
    expect(parseAreas(Array.from({ length: 13 }, (_, i) => `Area ${String.fromCharCode(65 + i)}`).join(",")).problem).toContain("twelve");
  });
});
