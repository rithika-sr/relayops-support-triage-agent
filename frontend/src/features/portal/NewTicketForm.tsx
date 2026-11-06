"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Field, Input, Notice, Select, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Account, Ticket } from "@/lib/types";

export const COMPONENTS = ["exports", "sso", "webhooks", "billing", "notifications", "api", "projects", "integrations"];

export function NewTicketForm({ accounts, onCreated }: { accounts?: Account[]; onCreated: (t: Ticket) => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ subject: "", body: "", reported_severity: "normal", component: "", product_version: "", error_code: "", customer_account_id: "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const m = useMutation<{ ticket: Ticket }, ApiError>({
    mutationFn: () => api.post("/tickets", { ...f, component: f.component || null, customer_account_id: f.customer_account_id || null }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["tickets"] });
      setF({ ...f, subject: "", body: "", error_code: "" });
      onCreated(r.ticket);
    },
  });
  const err = (field: string) => m.error?.errors?.find((e) => e.field === field)?.message;
  return (
    <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
      {m.error && !m.error.errors ? <Notice tone="danger">{m.error.detail}</Notice> : null}
      {accounts ? (
        <Field id="acct" label="Customer account">
          <Select id="acct" value={f.customer_account_id} onChange={set("customer_account_id")} required>
            <option value="">Choose an account…</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.plan}, {a.product_version})</option>)}
          </Select>
        </Field>
      ) : null}
      <Field id="subject" label="Subject" error={err("subject")}>
        <Input id="subject" value={f.subject} onChange={set("subject")} maxLength={300} required />
      </Field>
      <Field id="body" label="What happened?" hint="Steps, what you expected, and any error code you saw." error={err("body")}>
        <Textarea id="body" value={f.body} onChange={set("body")} maxLength={10000} required />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="severity" label="Impact">
          <Select id="severity" value={f.reported_severity} onChange={set("reported_severity")}>
            <option value="low">Low: question or minor issue</option>
            <option value="normal">Normal: something is not working</option>
            <option value="high">High: important work is blocked</option>
            <option value="critical">Critical: production is down</option>
          </Select>
        </Field>
        <Field id="component" label="Area (optional)">
          <Select id="component" value={f.component} onChange={set("component")}>
            <option value="">Not sure</option>
            {COMPONENTS.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
        </Field>
        <Field id="version" label="Product version (optional)" hint="Defaults to your account's version.">
          <Input id="version" value={f.product_version} onChange={set("product_version")} placeholder="e.g. 2.4" maxLength={32} />
        </Field>
        <Field id="error" label="Error code (optional)">
          <Input id="error" value={f.error_code} onChange={set("error_code")} placeholder="e.g. EXPORT_500" maxLength={80} />
        </Field>
      </div>
      <div><Button type="submit" variant="primary" busy={m.isPending} disabled={!f.subject || !f.body}>Submit ticket</Button></div>
    </form>
  );
}
