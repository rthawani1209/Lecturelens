import { Suspense } from "react";
import { WatchView } from "@/components/WatchView";

export default async function WatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <WatchView id={id} />
    </Suspense>
  );
}
