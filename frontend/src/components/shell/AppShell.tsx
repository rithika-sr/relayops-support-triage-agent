"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { cx, Loading } from "@/components/ui";
import { useLogout, useRequireRole } from "@/lib/session";
import type { Role } from "@/lib/types";

interface NavItem {
  href: string;
  label: string;
  roles: Role[];
  icon: string; // SVG path
}

const STAFF: Role[] = ["admin", "support"];

const NAV: NavItem[] = [
  { href: "/app", label: "Overview", roles: STAFF, icon: "M3 12l9-8 9 8v8a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z" },
  { href: "/app/inbox", label: "Inbox", roles: STAFF, icon: "M4 4h16v12h-5l-3 3-3-3H4z" },
  { href: "/app/investigations", label: "Investigations", roles: STAFF, icon: "M10 4a6 6 0 104.47 10l5.27 5.27 1.41-1.41L15.9 12.6A6 6 0 0010 4z" },
  { href: "/app/knowledge", label: "Knowledge", roles: STAFF, icon: "M5 4h10l4 4v12H5zM14 4v5h5" },
  { href: "/app/engineering", label: "Engineering", roles: STAFF, icon: "M4 6h7v5H4zM13 6h7v12h-7zM4 13h7v5H4z" },
  { href: "/app/incidents", label: "Incidents", roles: STAFF, icon: "M12 3l9 16H3zM12 10v4M12 17h.01" },
  { href: "/app/playbooks", label: "Playbooks", roles: STAFF, icon: "M6 4h12v16l-6-3-6 3z" },
  { href: "/app/artifacts", label: "Artifacts", roles: STAFF, icon: "M7 3h7l5 5v13H7zM9 13h8M9 17h6" },
  { href: "/app/evaluations", label: "Evaluations", roles: ["admin"], icon: "M4 20V10M10 20V4M16 20v-7M22 20H2" },
  { href: "/app/audit", label: "Audit", roles: ["admin"], icon: "M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z" },
  { href: "/app/settings", label: "Settings", roles: STAFF, icon: "M12 9a3 3 0 100 6 3 3 0 000-6zM4 12h2M18 12h2M12 4v2M12 18v2" },
];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={d} />
    </svg>
  );
}

export function Brand({ dark }: { dark?: boolean }) {
  return (
    <span className={cx("flex items-center gap-2 font-semibold tracking-tight", dark ? "text-white" : "text-ink-900")}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/relayops-mark.svg" alt="" className="size-7" />
      RelayOps
    </span>
  );
}

export function AppShell({ children, area }: { children: ReactNode; area: "staff" | "customer" }) {
  const me = useRequireRole(area === "staff" ? STAFF : ["customer"]);
  const logout = useLogout();
  const path = usePathname();
  // The mobile menu closes on navigation because its open state is tied to the path it was opened on.
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === path;

  if (!me.data || (area === "staff" ? !STAFF.includes(me.data.role) : me.data.role !== "customer")) {
    return <div className="p-8"><Loading label="Checking your session" /></div>;
  }
  const user = me.data;
  const items = area === "staff" ? NAV.filter((n) => n.roles.includes(user.role)) : [];
  const isActive = (href: string) => (href === "/app" || href === "/portal" ? path === href : path.startsWith(href));

  if (area === "customer") {
    return (
      <div className="min-h-screen">
        <header className="border-b border-ink-800 bg-ink-900">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
            <Link href="/portal"><Brand dark /></Link>
            <div className="flex items-center gap-3 text-sm text-ink-300">
              <span className="hidden sm:inline">{user.customer_account?.name} · {user.email}</span>
              <button onClick={logout} className="rounded-md border border-ink-700 px-2.5 py-1 text-white hover:bg-ink-800">Sign out</button>
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      </div>
    );
  }

  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {items.map((n) => (
        <Link
          key={n.href}
          href={n.href}
          aria-current={isActive(n.href) ? "page" : undefined}
          className={cx(
            "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm",
            isActive(n.href) ? "bg-ink-800 text-white" : "text-ink-300 hover:bg-ink-800/60 hover:text-white",
          )}
        >
          <Icon d={n.icon} />
          {n.label}
        </Link>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden w-56 shrink-0 flex-col bg-ink-900 px-3 py-4 lg:flex">
        <Link href="/app" className="mb-6 px-2"><Brand dark /></Link>
        {nav}
        <div className="mt-auto border-t border-ink-800 pt-3 text-xs text-ink-300">
          <p className="truncate px-2 font-medium text-white">{user.name}</p>
          <p className="truncate px-2">{user.organization.name} · {user.role}</p>
          <button onClick={logout} className="mt-2 w-full rounded-md px-2 py-1.5 text-left hover:bg-ink-800 hover:text-white">Sign out</button>
        </div>
      </aside>
      <header className="flex items-center justify-between bg-ink-900 px-4 py-3 lg:hidden">
        <Link href="/app"><Brand dark /></Link>
        <button
          className="rounded-md border border-ink-700 px-2.5 py-1 text-sm text-white"
          aria-expanded={open}
          aria-controls="mobile-nav"
          onClick={() => setOpenOn(open ? null : path)}
        >
          Menu
        </button>
      </header>
      {open ? (
        <div id="mobile-nav" className="bg-ink-900 px-3 pb-3 lg:hidden">
          {nav}
          <button onClick={logout} className="mt-2 w-full rounded-md px-2.5 py-1.5 text-left text-sm text-ink-300 hover:bg-ink-800">Sign out ({user.email})</button>
        </div>
      ) : null}
      <main className="min-w-0 flex-1 px-4 py-6 lg:px-8">{children}</main>
    </div>
  );
}
