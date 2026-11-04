import { Suspense } from "react";
import { StudyView } from "@/components/StudyView";

export const metadata = { title: "Study · LectureLens" };

export default function StudyPage() {
  return (
    <Suspense>
      <StudyView />
    </Suspense>
  );
}
