"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Card, ErrorState, Field, Loading, Notice, StatusBadge, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { TicketDetail } from "@/lib/types";

export function PortalTicket() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ticket", id], queryFn: () => api.get<TicketDetail>(`/tickets/${id}`), refetchInterval: 15_000 });
  const [body, setBody] = useState("");
  const send = useMutation<unknown, ApiError>({
    mutationFn: () => api.post(`/tickets/${id}/messages`, { body }),
    onSuccess: () => { setBody(""); qc.invalidateQueries({ queryKey: ["ticket", id] }); },
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const d = q.data!;
  return (
    <div className="flex flex-col gap-4">
      <Link href="/portal" className="text-sm text-accent-700 hover:underline">← All tickets</Link>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{d.ticket.subject}</h1>
        <StatusBadge status={d.ticket.status === "pending_review" ? "open" : d.ticket.status} />
      </div>
      <p className="text-sm text-muted">#{d.ticket.number} · opened {fmtDate(d.ticket.created_at)} · {d.ticket.component ?? "general"} · version {d.ticket.product_version ?? "—"}</p>
      {d.incidents.map((i) => (
        <Notice key={i.id} tone="warn"><span className="font-medium">{i.title}:</span> {i.public_summary}</Notice>
      ))}
      <Card title="Conversation">
        <ol className="flex flex-col gap-3">
          {d.messages.map((m) => (
            <li key={m.id} className={m.author_kind === "customer" ? "self-end max-w-[85%]" : "max-w-[85%]"}>
              <div className={m.author_kind === "customer" ? "rounded-lg bg-accent-50 px-3 py-2" : "rounded-lg border border-line bg-white px-3 py-2"}>
                <p className="text-xs font-medium text-muted">{m.author_kind === "customer" ? "You" : "TaskFlow support"} · {fmtDate(m.created_at)}</p>
                <p className="mt-1 text-sm whitespace-pre-wrap">{m.body}</p>
              </div>
            </li>
          ))}
        </ol>
        {d.messages.every((m) => m.author_kind === "customer") ? (
          <p className="mt-3 text-sm text-muted">Support has your ticket. Replies appear here once a team member has reviewed them.</p>
        ) : null}
      </Card>
      <Card title="Add a reply">
        <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
          {send.error ? <Notice tone="danger">{send.error.detail}</Notice> : null}
          <Field id="reply" label="Message" hint="New details help support; they also mean any pending draft is re-checked.">
            <Textarea id="reply" value={body} onChange={(e) => setBody(e.target.value)} maxLength={10000} />
          </Field>
          <div><Button variant="primary" type="submit" busy={send.isPending} disabled={!body.trim()}>Send</Button></div>
        </form>
      </Card>
    </div>
  );
}
