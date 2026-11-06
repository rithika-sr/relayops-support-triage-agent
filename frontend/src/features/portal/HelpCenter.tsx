"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Button, Card, Empty, ErrorState, Field, Input, Loading, Notice, PageHeader, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/format";

interface Result { document_id: string; title: string; kind: string; excerpt: string }
interface Search { query: string; results: Result[] }
interface Article { document_id: string; title: string; content: string; version: number; updated_at: string }

function Contact({ query, documentId }: { query: string; documentId?: string }) {
  const [subject, setSubject] = useState(query ? `Question: ${query}`.slice(0, 120) : "");
  const [body, setBody] = useState("");
  const send = useMutation<{ ticket_id: string; number: number }, ApiError>({
    mutationFn: () => api.post("/portal/help/contact", { subject, body, document_id: documentId ?? null, query: query || null }),
  });
  if (send.data) {
    return <Notice tone="ok" title={`Ticket #${send.data.number} opened`}>Support will reply on the ticket after review. <Link className="underline" href={`/portal/tickets/${send.data.ticket_id}`}>Open it</Link>.</Notice>;
  }
  return (
    <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
      <Field id="hc-subject" label="Subject"><Input id="hc-subject" value={subject} onChange={(e) => setSubject(e.target.value)} /></Field>
      <Field id="hc-body" label="What is going on?" hint="Support sees which article and search you came from."><Textarea id="hc-body" value={body} onChange={(e) => setBody(e.target.value)} /></Field>
      {send.error ? <Notice tone="danger">{send.error.detail}</Notice> : null}
      <Button type="submit" variant="primary" disabled={subject.trim().length < 3 || !body.trim()} busy={send.isPending}>Contact support</Button>
    </form>
  );
}

function ArticleView({ id, query, onBack }: { id: string; query: string; onBack: () => void }) {
  const q = useQuery({ queryKey: ["help-article", id], queryFn: () => api.get<Article>(`/portal/help/articles/${id}`) });
  const [vote, setVote] = useState<boolean | null>(null);
  const [contact, setContact] = useState(false);
  const fb = useMutation<unknown, ApiError, boolean>({
    mutationFn: (helpful) => api.post(`/portal/help/articles/${id}/feedback`, { helpful }),
    onSuccess: (_, helpful) => { setVote(helpful); if (!helpful) setContact(true); },
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const a = q.data!;
  return (
    <div className="flex flex-col gap-4">
      <button className="self-start text-sm text-accent-700 hover:underline" onClick={onBack}>← Back to results</button>
      <Card title={a.title}>
        <p className="mb-3 text-xs text-muted">Updated {fmtDate(a.updated_at)} · version {a.version}</p>
        <div className="whitespace-pre-wrap text-[15px] leading-relaxed">{a.content}</div>
      </Card>
      <div className="flex flex-wrap items-center gap-2 text-sm" aria-live="polite">
        {vote === null ? (
          <>
            <span>Did this answer your question?</span>
            <Button size="sm" onClick={() => fb.mutate(true)} busy={fb.isPending}>Yes</Button>
            <Button size="sm" onClick={() => fb.mutate(false)} busy={fb.isPending}>No</Button>
          </>
        ) : <span className="text-muted">{vote ? "Thanks for letting us know." : "Sorry it did not help. Tell support below."}</span>}
      </div>
      {contact ? <Card title="Still need help?"><Contact query={query} documentId={id} /></Card> : (
        <button className="self-start text-sm text-accent-700 hover:underline" onClick={() => setContact(true)}>Still need help? Contact support</button>
      )}
    </div>
  );
}

export function HelpCenter() {
  const [text, setText] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const search = useMutation<Search, ApiError, string>({ mutationFn: (q) => api.get(`/portal/help/search?q=${encodeURIComponent(q)}`) });
  const query = search.data?.query ?? "";
  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Help" subtitle="Search current articles. If nothing fits, contact support from here and we will see what you looked at." />
      {open ? <ArticleView id={open} query={query} onBack={() => setOpen(null)} /> : (
        <>
          <form role="search" className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim().length >= 2) search.mutate(text.trim()); }}>
            <label htmlFor="help-q" className="sr-only">Search Help</label>
            <Input id="help-q" className="min-w-0 flex-1" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. export row limit" />
            <Button type="submit" variant="primary" busy={search.isPending}>Search</Button>
          </form>
          {search.error ? <ErrorState error={search.error} /> : null}
          {search.data ? (
            search.data.results.length === 0 ? (
              <Card title={`No articles for “${query}”`}><Contact query={query} /></Card>
            ) : (
              <>
                <ul className="flex flex-col gap-2">
                  {search.data.results.map((r) => (
                    <li key={r.document_id}>
                      <button className="w-full rounded-lg border border-line bg-card px-4 py-3 text-left hover:border-accent-600" onClick={() => setOpen(r.document_id)}>
                        <span className="block font-medium">{r.title}</span>
                        <span className="mt-1 line-clamp-2 block text-sm text-muted">{r.excerpt}</span>
                      </button>
                    </li>
                  ))}
                </ul>
                <details className="text-sm"><summary className="cursor-pointer text-accent-700">None of these help? Contact support</summary><div className="mt-3"><Contact query={query} /></div></details>
              </>
            )
          ) : <Empty title="Search for an answer">Articles are the current published versions for your plan.</Empty>}
        </>
      )}
    </div>
  );
}
