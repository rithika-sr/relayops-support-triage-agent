import Link from "next/link";
import { Brand } from "@/components/shell/AppShell";

const FEATURES = [
  {
    title: "Account-aware investigation",
    body: "A bounded local-model agent reads only what this customer's account and your organization allow: current policy, entitlements, known issues, incidents, deployments, and error aggregates.",
  },
  {
    title: "Evidence you can inspect",
    body: "Every tool call, observation, citation, and computed fact is persisted with its source version and hash. Correlation is labeled as correlation, never as root cause.",
  },
  {
    title: "Version-bound review",
    body: "Approval binds the exact ticket revision, draft version, destination, and payload hash. Edit the draft and the old approval no longer applies.",
  },
  {
    title: "Recoverable actions",
    body: "Approved replies become customer-visible messages in this app and handoffs become local engineering records, exactly once, through an action ledger.",
  },
  {
    title: "Incident constellations",
    body: "Related reports group by component, error signature, version, and time window with correct distinct-account counts, and stay candidates until someone reviews them.",
  },
  {
    title: "Measured, not assumed",
    body: "Recorded replay, comparison runs, and a baseline-driven evaluation harness report real denominators and leave unrun cases marked unrun.",
  },
];

export default function Landing() {
  return (
    <div className="min-h-screen">
      <header className="bg-ink-900">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <Brand dark />
          <nav className="flex items-center gap-2 text-sm">
            <Link href="/login" className="rounded-md px-3 py-1.5 text-ink-300 hover:text-white">Sign in</Link>
            <Link href="/register" className="rounded-md bg-accent-700 px-3 py-1.5 font-medium text-white hover:bg-accent-600">Create organization</Link>
          </nav>
        </div>
        <div className="mx-auto max-w-6xl px-4 pt-10 pb-16">
          <p className="text-sm font-medium tracking-wide text-accent-100 uppercase">Support to engineering, with receipts</p>
          <h1 className="mt-3 max-w-3xl text-3xl leading-tight font-semibold text-white sm:text-5xl">
            Turn a customer report into a reviewed answer or a complete engineering handoff.
          </h1>
          <p className="mt-5 max-w-2xl text-base text-ink-300 sm:text-lg">
            RelayOps runs a bounded investigation on a local model, shows the evidence behind every claim, pauses for a
            human, and records exactly what was approved and done.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/login" className="rounded-md bg-accent-700 px-4 py-2 font-medium text-white hover:bg-accent-600">Sign in to the workbench</Link>
            <Link href="/register" className="rounded-md border border-ink-700 px-4 py-2 font-medium text-white hover:bg-ink-800">Start a new organization</Link>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-14">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <article key={f.title} className="rounded-lg border border-line bg-card p-5">
              <h2 className="font-semibold">{f.title}</h2>
              <p className="mt-2 text-sm text-muted">{f.body}</p>
            </article>
          ))}
        </div>
        <section className="mt-12 rounded-lg border border-line bg-card p-6">
          <h2 className="font-semibold">How a ticket moves</h2>
          <ol className="mt-4 grid gap-3 text-sm sm:grid-cols-5">
            {["Customer reports in the portal", "Support launches a playbook", "Agent gathers authorized evidence", "Reviewer edits or approves the exact draft", "Customer sees the approved reply"].map((s, i) => (
              <li key={s} className="flex gap-2">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-warn-100 text-xs font-semibold text-warn-700">{i + 1}</span>
                <span>{s}</span>
              </li>
            ))}
          </ol>
        </section>
        <p className="mt-10 text-xs text-muted">
          Local alpha. Demo data is synthetic. Actions are local to this application: RelayOps does not send email or write
          to external trackers.
        </p>
      </main>
    </div>
  );
}
