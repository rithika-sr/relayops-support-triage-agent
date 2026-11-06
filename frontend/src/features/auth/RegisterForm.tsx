"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Field, Input, Notice } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Me } from "@/lib/types";
import { AuthFrame } from "./AuthFrame";

export function RegisterForm() {
  const router = useRouter();
  const qc = useQueryClient();
  const invite = useSearchParams().get("invite");
  const [form, setForm] = useState({ name: "", email: "", password: "", organization_name: "" });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  const fieldError = (f: string) => error?.errors?.find((x) => x.field === f)?.message;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = invite
        ? await api.post<{ user: Me; redirect_to: string }>("/auth/accept-invitation", { token: invite, name: form.name, password: form.password })
        : await api.post<{ user: Me; redirect_to: string }>("/auth/register", form);
      qc.setQueryData(["me"], res.user);
      router.replace(res.redirect_to);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, { detail: "Could not reach the server." }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame
      title={invite ? "Accept your invitation" : "Create an organization"}
      footer={<>Already have an account? <Link className="font-medium text-teal-700 underline" href="/login">Sign in</Link></>}
    >
      <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
        {error && !error.errors ? <Notice tone="danger">{error.detail}</Notice> : null}
        {invite ? (
          <Notice tone="teal">You were invited to a customer account. Your email comes from the invitation.</Notice>
        ) : (
          <p className="text-sm text-muted">You become the admin of a new, empty organization. Joining an existing organization requires an invitation.</p>
        )}
        <Field id="name" label="Your name" error={fieldError("name")}>
          <Input id="name" autoComplete="name" value={form.name} onChange={set("name")} required />
        </Field>
        {!invite ? (
          <>
            <Field id="email" label="Work email" error={fieldError("email")}>
              <Input id="email" type="email" autoComplete="email" value={form.email} onChange={set("email")} required />
            </Field>
            <Field id="org" label="Organization name" error={fieldError("organization_name")}>
              <Input id="org" value={form.organization_name} onChange={set("organization_name")} required />
            </Field>
          </>
        ) : null}
        <Field id="password" label="Password" hint="At least 12 characters." error={fieldError("password")}>
          <Input id="password" type="password" autoComplete="new-password" value={form.password} onChange={set("password")} required />
        </Field>
        <Button type="submit" variant="primary" busy={busy}>{invite ? "Join" : "Create organization"}</Button>
      </form>
    </AuthFrame>
  );
}
