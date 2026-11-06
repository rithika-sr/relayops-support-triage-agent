import { Suspense } from "react";
import { InboxPage } from "@/features/tickets/InboxPage";

export default function Page() {
  return (
    <Suspense>
      <InboxPage />
    </Suspense>
  );
}
