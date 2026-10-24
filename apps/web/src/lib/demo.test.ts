import { describe, expect, it } from "vitest";
import { demoBase, matched, refreshedOn, years } from "./demo";

describe("demo venue summaries", () => {
  it("shows the span of years, whatever precision MusicBrainz gave the dates", () => {
    expect(years({ first: "1997-09-03", last: "2026-10-23" })).toBe("1997 to 2026");
    expect(years({ first: "2003", last: "2026-03" })).toBe("2003 to 2026");
    expect(years({ first: "2019-05-01", last: "2019-11-30" })).toBe("2019");
  });

  it("says nothing rather than guessing when a date is missing", () => {
    expect(years({})).toBeNull();
    expect(years({ first: "2001-01-01" })).toBeNull();
    expect(years({ first: null, last: null })).toBeNull();
  });

  it("counts matched performers only when both figures exist", () => {
    expect(matched({ acts_matched: 89, performers: 120 })).toBe("89 of 120 matched");
    expect(matched({ acts_matched: 0, performers: 5 })).toBe("0 of 5 matched");
    expect(matched({ acts_matched: 3 })).toBeNull();
    expect(matched({})).toBeNull();
  });

  it("formats the rebuild date, and ignores a missing or broken one", () => {
    expect(refreshedOn("2026-10-24T12:00:00Z")).toBe("24 October 2026");
    expect(refreshedOn(null)).toBeNull();
    expect(refreshedOn("not a date")).toBeNull();
  });

  it("points at the public routes of a venue", () => {
    expect(demoBase("mercury-lounge")).toBe("/public/demo/mercury-lounge");
  });
});
