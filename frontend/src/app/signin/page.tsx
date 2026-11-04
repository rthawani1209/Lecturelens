import { Suspense } from "react";
import { SignIn } from "@/components/SignIn";

export const metadata = { title: "Sign in · LectureLens" };

export default function SignInPage() {
  return (
    <Suspense>
      <SignIn />
    </Suspense>
  );
}
