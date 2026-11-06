// Information architecture: seven primary destinations, each with secondary tabs.
// Existing URLs stay valid; each URL belongs to exactly one section.

import type { Role } from "@/lib/types";

export interface NavTab {
  href: string;
  label: string;
  roles?: Role[];
}

export interface NavSection {
  id: string;
  label: string;
  href: string;
  icon: string; // SVG path
  roles: Role[];
  tabs: NavTab[];
}

const STAFF: Role[] = ["admin", "support"];

export const SECTIONS: NavSection[] = [
  { id: "home", label: "Home", href: "/app", roles: STAFF, icon: "M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z",
    tabs: [] },
  { id: "support", label: "Support", href: "/app/inbox", roles: STAFF, icon: "M4 5h16v11h-6l-4 3v-3H4z",
    tabs: [
      { href: "/app/inbox", label: "Inbox" },
      { href: "/app/investigations", label: "Investigations" },
      { href: "/app/artifacts", label: "Drafts & exports" },
      { href: "/app/playbooks", label: "Playbooks" },
      { href: "/app/imports", label: "Imports" },
    ] },
  // PENDING-success  { id: "success", label: "Customer Success", href: "/app/success", roles: STAFF,
//     icon: "M12 21s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 11c0 5.6-7 10-7 10z",
//     tabs: [
//       { href: "/app/success", label: "Accounts" },
//       { href: "/app/success/opportunities", label: "Opportunities" },
//       { href: "/app/success/experiments", label: "Experiments" },
//     ] },
  { id: "knowledge", label: "Knowledge", href: "/app/knowledge", roles: STAFF, icon: "M5 4h10l4 4v12H5zM14 4v5h5",
    tabs: [{ href: "/app/knowledge", label: "Library and search" }] },
  { id: "engineering", label: "Engineering", href: "/app/engineering", roles: STAFF, icon: "M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12",
    tabs: [{ href: "/app/engineering", label: "Issues and handoffs" }, { href: "/app/incidents", label: "Incidents" }] },
  { id: "analytics", label: "Analytics", href: "/app/analytics", roles: STAFF, icon: "M4 20V10M10 20V4M16 20v-7M21 20H3",
    tabs: [
      { href: "/app/analytics", label: "Operations" },
      { href: "/app/evaluations", label: "Model quality", roles: ["admin"] },
    ] },
  { id: "settings", label: "Settings", href: "/app/settings", roles: STAFF,
    icon: "M12 9a3 3 0 100 6 3 3 0 000-6zM19 12l2-1-1-3-2 .5-1.5-1.5L17 5l-3-1-1 2h-2L10 4 7 5l.5 2L6 8.5 4 8l-1 3 2 1v0l-2 1 1 3 2-.5L7.5 17 7 19l3 1 1-2h2l1 2 3-1-.5-2 1.5-1.5 2 .5 1-3z",
    tabs: [
      { href: "/app/settings", label: "General" },
      { href: "/app/settings/integrations", label: "Integrations" },
      { href: "/app/audit", label: "Audit", roles: ["admin"] },
    ] },
];

export function sectionFor(path: string): NavSection | undefined {
  let best: NavSection | undefined;
  let bestLen = -1;
  for (const s of SECTIONS) {
    for (const href of [s.href, ...s.tabs.map((t) => t.href)]) {
      const match = href === "/app" ? path === "/app" : path === href || path.startsWith(href + "/");
      if (match && href.length > bestLen) {
        best = s;
        bestLen = href.length;
      }
    }
  }
  if (!best && path.startsWith("/app/tickets")) return SECTIONS.find((s) => s.id === "support");
  return best;
}
