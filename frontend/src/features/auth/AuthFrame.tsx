import Link from "next/link";
import type { ReactNode } from "react";
import { Brand } from "@/components/shell/AppShell";

export function AuthFrame({ title, children, footer }: { title: string; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 py-10">
      <Link href="/" className="mb-6"><Brand /></Link>
      <div className="w-full max-w-sm rounded-lg border border-line bg-card p-6 shadow-sm">
        <h1 className="mb-4 text-lg font-semibold">{title}</h1>
        {children}
      </div>
      <div className="mt-4 text-sm text-muted">{footer}</div>
    </div>
  );
}
