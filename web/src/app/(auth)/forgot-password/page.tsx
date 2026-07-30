"use client";

import { useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { DevOtpNote, OtpInput } from "@/components/auth/OtpInput";
import { PasswordHints, passwordOk } from "@/components/auth/PasswordHints";
import { useCooldown } from "@/components/auth/useCooldown";

const NETWORK_MSG = "Could not reach the server. Is the backend running?";

export default function ForgotPasswordPage() {
  const [step, setStep] = useState<"email" | "reset" | "done">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Always the backend's anti-enumeration generic - never reveals whether the
  // account exists.
  const [note, setNote] = useState<string | null>(null);
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const cooldown = useCooldown(30);

  async function submitEmail(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.forgotPassword(email);
      setNote(r.detail);
      setDevOtp(r.dev_otp ?? null);
      setCode("");
      setStep("reset");
      cooldown.start();
    } catch (err) {
      // 429 throttle details surface verbatim.
      setError(err instanceof ApiError ? err.message : NETWORK_MSG);
    } finally {
      setBusy(false);
    }
  }

  // Re-requests a reset code via forgot-password (the "R" channel) — NOT the
  // signup resend endpoint, whose "V" codes the reset screen would reject.
  async function resend() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.forgotPassword(email);
      setNote(r.detail);
      setDevOtp(r.dev_otp ?? null);
      cooldown.start();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : NETWORK_MSG);
      // The server throttle (3/email per 10 min) outlasts the 30s button
      // cooldown; arm it on a 429 too so the button can't be hammered.
      if (err instanceof ApiError && err.status === 429) cooldown.start();
    } finally {
      setBusy(false);
    }
  }

  async function submitReset(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.resetPassword(email, code, password);
      setStep("done");
    } catch (err) {
      // 400 ("Invalid code", "Code expired…") / 429 details verbatim.
      setError(err instanceof ApiError ? err.message : NETWORK_MSG);
    } finally {
      setBusy(false);
    }
  }

  if (step === "done") {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="display text-3xl">
            Password <em>updated</em>
          </h1>
        </div>
        <div className="flex items-center gap-3 rounded-2xl border border-line bg-paper px-5 py-4">
          <Check aria-hidden className="size-5 shrink-0 text-moss" />
          <p className="text-sm text-ink-soft">
            Your password has been reset. Sign in with the new one.
          </p>
        </div>
        <Link
          href="/login"
          className="inline-flex items-center justify-center rounded-full bg-ink px-4 py-2 text-sm font-medium text-cream transition hover:opacity-90"
        >
          Sign in
        </Link>
      </div>
    );
  }

  if (step === "reset") {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="display text-3xl">
            Reset your <em>password</em>
          </h1>
          {note && <p className="mt-2 text-sm text-ink-soft">{note}</p>}
        </div>
        {devOtp && <DevOtpNote code={devOtp} onFill={() => setCode(devOtp)} />}
        <form onSubmit={submitReset} className="space-y-4">
          {/* No htmlFor: OtpInput's boxes carry their own aria-labels. */}
          <Field label="Reset code">
            <OtpInput value={code} onChange={setCode} disabled={busy} />
          </Field>
          <Field label="New password" htmlFor="reset-password">
            <Input
              id="reset-password"
              type="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <PasswordHints password={password} />

          {error && (
            <p className="text-sm text-rust" role="alert">
              {error}
            </p>
          )}

          <Button
            type="submit"
            busy={busy}
            disabled={code.length !== 6 || !passwordOk(password)}
            className="w-full"
          >
            Reset password
          </Button>
        </form>
        <div className="flex items-center justify-between gap-3">
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              setError(null); // a stale "Invalid code" must not read as an email error
              setStep("email");
            }}
          >
            &larr; Use a different email
          </Button>
          <Button variant="ghost" disabled={cooldown.active || busy} onClick={resend}>
            {cooldown.active ? `Resend in ${cooldown.remaining}s` : "Resend code"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="display text-3xl">
          Forgot your <em>password?</em>
        </h1>
        <p className="mt-2 text-sm text-ink-soft">
          Enter your account email and we&rsquo;ll send a 6-digit reset code.
        </p>
      </div>

      <form onSubmit={submitEmail} className="space-y-4">
        <Field label="Email" htmlFor="forgot-email">
          <Input
            id="forgot-email"
            type="email"
            suppressHydrationWarning
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>

        {error && (
          <p className="text-sm text-rust" role="alert">
            {error}
          </p>
        )}

        <Button type="submit" busy={busy} className="w-full">
          Send reset code
        </Button>
      </form>

      <p className="text-sm text-ink-soft">
        Remembered it?{" "}
        <Link href="/login" className="font-medium text-ink underline underline-offset-2">
          Sign in
        </Link>
      </p>
    </div>
  );
}
