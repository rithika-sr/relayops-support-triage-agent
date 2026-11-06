"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { cx, Loading } from "@/components/ui";
import { useInstance } from "@/lib/instance";
import { SECTIONS, sectionFor } from "@/lib/nav";
import { useLogout, useRequireRole } from "@/lib/session";
import type { Role } from "@/lib/types";

const STAFF: Role[] = ["admin", "support"];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="size-[18px] shrink-0" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={d} />
    </svg>
  );
}

export function Brand({ dark }: { dark?: boolean }) {
  return (
    <span className={cx("flex items-center gap-2 font-semibold tracking-tight", dark ? "text-white" : "text-text")}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/relayops-mark.svg" alt="" className="size-7" />
      RelayOps
    </span>
  );
}

/** Persistent label for demo and test instances. Operational instances show nothing. */
export function InstanceBanner() {
  const inst = useInstance();
  if (!inst.data || inst.data.data_mode === "operational") return null;
  return (
    <div role="note" className="bg-warn-100 px-4 py-1.5 text-center text-[13px] font-medium text-warn-700">
      {inst.data.banner}
    </div>
  );
}

function SectionTabs({ path, role }: { path: string; role: Role }) {
  const section = sectionFor(path);
  const tabs = section?.tabs.filter((t) => !t.roles || t.roles.includes(role)) ?? [];
  if (tabs.length < 2) return null;
  const active = tabs.reduce<string | null>((best, t) => ((path === t.href || path.startsWith(t.href + "/")) && t.href.length > (best?.length ?? 0) ? t.href : best), null);
  return (
    <nav aria-label={`${section?.label} sections`} className="mb-5 flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <Link key={t.href} href={t.href} aria-current={active === t.href ? "page" : undefined}
          className={cx("-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap", active === t.href ? "border-accent-600 font-medium text-text" : "border-transparent text-muted hover:text-text")}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

export function AppShell({ children, area }: { children: ReactNode; area: "staff" | "customer" }) {
  const me = useRequireRole(area === "staff" ? STAFF : ["customer"]);
  const logout = useLogout();
  const path = usePathname();
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === path;

  if (!me.data || (area === "staff" ? !STAFF.includes(me.data.role) : me.data.role !== "customer")) {
    return <div className="p-8"><Loading label="Checking your session" /></div>;
  }
  const user = me.data;

  if (area === "customer") {
    return (
      <div className="min-h-screen">
        <InstanceBanner />
        <header className="border-b border-line bg-card">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
            <Link href="/portal"><Brand /></Link>
            <nav aria-label="Portal" className="flex items-center gap-1 text-sm">
              <Link href="/portal" className={cx("rounded-md px-2.5 py-1.5", path === "/portal" ? "bg-sunken font-medium" : "text-muted hover:text-text")}>My tickets</Link>
              <Link href="/portal/help" className={cx("rounded-md px-2.5 py-1.5", path.startsWith("/portal/help") ? "bg-sunken font-medium" : "text-muted hover:text-text")}>Help</Link>
              <button onClick={logout} className="ml-2 rounded-md border border-line-strong px-2.5 py-1.5 hover:bg-sunken">Sign out</button>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      </div>
    );
  }

  const sections = SECTIONS.filter((s) => s.roles.includes(user.role));
  const current = sectionFor(path);
  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {sections.map((s) => (
        <Link key={s.id} href={s.href} aria-current={current?.id === s.id ? "page" : undefined}
          className={cx("flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm", current?.id === s.id ? "bg-accent-50 font-medium text-accent-700" : "text-ink-700 hover:bg-sunken")}>
          <Icon d={s.icon} />
          {s.label}
        </Link>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen">
      <InstanceBanner />
      <div className="lg:flex">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-card px-3 py-4 lg:flex">
          <Link href="/app" className="mb-6 px-2"><Brand /></Link>
          {nav}
          <div className="mt-auto border-t border-line pt-3 text-[13px]">
            <p className="truncate px-2 font-medium">{user.name}</p>
            <p className="truncate px-2 text-muted">{user.organization.name} · {user.role}</p>
            <button onClick={logout} className="mt-2 w-full rounded-md px-2 py-1.5 text-left text-muted hover:bg-sunken hover:text-text">Sign out</button>
          </div>
        </aside>
        <header className="flex items-center justify-between border-b border-line bg-card px-4 py-3 lg:hidden">
          <Link href="/app"><Brand /></Link>
          <button className="rounded-md border border-line-strong px-3 py-1.5 text-sm" aria-expanded={open} aria-controls="mobile-nav" onClick={() => setOpenOn(open ? null : path)}>
            Menu
          </button>
        </header>
        {open ? (
          <div id="mobile-nav" className="border-b border-line bg-card px-3 pb-3 lg:hidden">
            {nav}
            <button onClick={logout} className="mt-2 w-full rounded-md px-2.5 py-2 text-left text-sm text-muted hover:bg-sunken">Sign out ({user.email})</button>
          </div>
        ) : null}
        <main className="min-w-0 flex-1 px-4 py-6 lg:px-10">
          <div className="mx-auto max-w-[1280px]">
            <SectionTabs path={path} role={user.role} />
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
