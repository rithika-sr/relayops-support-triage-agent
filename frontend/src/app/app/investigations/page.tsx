import { Suspense } from "react";
import { InvestigationsList } from "@/features/investigations/InvestigationsList";

export default function Page() {
  return (
    <Suspense>
      <InvestigationsList />
    </Suspense>
  );
}
