import { Suspense } from "react";
import { UploadView } from "@/components/UploadView";

export const metadata = { title: "Add a lecture · LectureLens" };

export default function UploadPage() {
  return (
    <Suspense>
      <UploadView />
    </Suspense>
  );
}
