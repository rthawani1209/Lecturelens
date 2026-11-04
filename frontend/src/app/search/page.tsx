import { Suspense } from "react";
import { SearchView } from "@/components/SearchView";
import { api, type Course } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SearchPage() {
  const courses: Course[] = await api.publicCourses().catch(() => []);
  return (
    <Suspense>
      <SearchView courses={courses} />
    </Suspense>
  );
}
