import { AppShell } from "@/components/shell/AppShell";

export default function StaffLayout({ children }: { children: React.ReactNode }) {
  return <AppShell area="staff">{children}</AppShell>;
}
