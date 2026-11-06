import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Player } from "./Player";

const props = { start: 0, length: 60, transcript: [], tag: null, onTime: () => undefined };

describe("Player", () => {
  it("keeps its link until it fails, then takes the fresh one", () => {
    URL.createObjectURL = () => "blob:vtt";
    URL.revokeObjectURL = () => undefined;
    const onExpired = vi.fn();
    const first = "/api/media/v.mp4?exp=1&sig=a";
    const later = "/api/media/v.mp4?exp=2&sig=b";
    const { container, rerender } = render(<Player {...props} src={first} onExpired={onExpired} />);
    const video = () => container.querySelector("video")!;

    // a periodic refresh: same video, new signature. Swapping would restart playback.
    rerender(<Player {...props} src={later} onExpired={onExpired} />);
    expect(video().getAttribute("src")).toBe(first);

    // the old link expires mid-lecture: ask for a new one and use it
    fireEvent.error(video());
    expect(onExpired).toHaveBeenCalledOnce();
    const fresh = "/api/media/v.mp4?exp=3&sig=c";
    rerender(<Player {...props} src={fresh} onExpired={onExpired} />);
    expect(video().getAttribute("src")).toBe(fresh);

    // a different video swaps straight away
    rerender(<Player {...props} src="/api/media/w.mp4?exp=3&sig=d" onExpired={onExpired} />);
    expect(video().getAttribute("src")).toContain("w.mp4");
  });
});
