"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Field, Input, Notice } from "@/components/ui";
import { api, ApiError, safeNext } from "@/lib/api";
import type { Me } from "@/lib/types";
import { AuthFrame } from "./AuthFrame";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ user: Me; redirect_to: string }>("/auth/login", { email, password, next: params.get("next") });
      qc.setQueryData(["me"], res.user);
      router.replace(safeNext(res.redirect_to, res.user.role));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not reach the server. Is the API running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame title="Sign in" footer={<>New here? <Link className="font-medium text-accent-700 underline" href="/register">Create an organization</Link></>}>
      <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
        {error ? <Notice tone="danger">{error}</Notice> : null}
        <Field id="email" label="Email">
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field id="password" label="Password">
          <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Button type="submit" variant="primary" busy={busy} disabled={!email || !password}>Sign in</Button>
        <p className="text-xs text-muted">
          Password reset is not available in this local alpha. An organization admin can issue a new invitation.
        </p>
      </form>
    </AuthFrame>
  );
}
