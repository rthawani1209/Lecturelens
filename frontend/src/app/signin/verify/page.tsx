import { Suspense } from "react";
import { VerifyLink } from "@/components/SignIn";

export const metadata = { title: "Signing in · LectureLens" };

export default function VerifyPage() {
  return (
    <Suspense>
      <VerifyLink />
    </Suspense>
  );
}
