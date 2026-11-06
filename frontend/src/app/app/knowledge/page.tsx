import { Suspense } from "react";
import { KnowledgePage } from "@/features/knowledge/KnowledgePage";

export default function Page() {
  return (
    <Suspense>
      <KnowledgePage />
    </Suspense>
  );
}
