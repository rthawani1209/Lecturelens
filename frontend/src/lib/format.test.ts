import { describe, expect, it } from "vitest";
import { highlight, position, safeNext, timecode } from "./format";

describe("timecode", () => {
  it("formats minutes and hours", () => {
    expect(timecode(1599.4)).toBe("26:39");
    expect(timecode(5)).toBe("0:05");
    expect(timecode(3725)).toBe("1:02:05");
    expect(timecode(-3)).toBe("0:00");
  });
});

describe("position", () => {
  it("clamps to the bar and survives a missing length", () => {
    expect(position(1599, 3452)).toBe("46.3%");
    expect(position(9999, 100)).toBe("100.0%");
    expect(position(10, null)).toBe("0%");
  });
});

describe("highlight", () => {
  it("marks query words, ignoring stop words and plurals", () => {
    const parts = highlight(
      "graphs that have positive edge weights. Okay?",
      "why negative edge weight",
    );
    expect(parts.filter((p) => p.hit).map((p) => p.text)).toEqual(["edge weights"]);
    expect(parts.map((p) => p.text).join("")).toBe("graphs that have positive edge weights. Okay?");
  });

  it("returns the sentence untouched when nothing matches", () => {
    expect(highlight("hello there", "dijkstra")).toEqual([{ text: "hello there", hit: false }]);
  });
});

describe("safeNext", () => {
  it("keeps same-site paths and drops everything else", () => {
    expect(safeNext("/study?lecture=1")).toBe("/study?lecture=1");
    const bad = ["//evil.com", "/\\evil.com", "/\t/evil.com", "/\n/evil.com", "https://evil.com"];
    for (const b of [...bad, "evil", "", null]) {
      expect(safeNext(b)).toBe("/");
    }
  });
});
