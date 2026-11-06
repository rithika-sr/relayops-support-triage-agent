import { AppShell } from "@/components/shell/AppShell";

export const metadata = { title: "Support portal" };

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return <AppShell area="customer">{children}</AppShell>;
}
