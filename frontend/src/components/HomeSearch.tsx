"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Mode } from "@/lib/api";
import { SearchBox } from "./SearchBox";

export function HomeSearch({ courseId }: { courseId?: string }) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("meaning");
  return (
    <SearchBox
      mode={mode}
      onModeChange={setMode}
      onSubmit={(q) => {
        const p = new URLSearchParams({ q });
        if (mode !== "meaning") p.set("mode", mode);
        if (courseId) p.set("course", courseId);
        router.push(`/search?${p}`);
      }}
    />
  );
}
