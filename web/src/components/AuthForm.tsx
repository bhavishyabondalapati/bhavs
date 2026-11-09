"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

type Mode = "login" | "signup";

async function post(url: string, body: object) {
  const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

export default function AuthForm({ mode, next = "/" }: { mode: Mode; next?: string }) {
  const router = useRouter();
  const [step, setStep] = useState<"details" | "code">("details");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function signIn() {
    const r = await post("/api/auth/login", { email, password });
    if (r.ok) {
      router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
      router.refresh();
      return;
    }
    if (r.data.code === "UserNotConfirmedException") {
      setStep("code");
      setError("Enter the 6-digit code we emailed you to finish creating your account.");
    } else setError(r.data.error ?? "Could not sign in.");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "login") await signIn();
      else if (step === "details") {
        const r = await post("/api/auth/signup", { email, password });
        if (r.ok) setStep("code");
        else setError(r.data.error ?? "Could not sign up.");
      } else {
        const r = await post("/api/auth/confirm", { email, code });
        if (r.ok) await signIn();
        else setError(r.data.error ?? "Could not confirm.");
      }
    } finally {
      setBusy(false);
    }
  }

  const confirming = step === "code";
  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <h1>{mode === "login" ? "Welcome back" : confirming ? "Check your email" : "Create your account"}</h1>
        <p className="lead">
          {mode === "login" ? "Sign in to keep watching." : confirming ? `We sent a 6-digit code to ${email}.` : "Free, and built for open-licensed films."}
        </p>
        <form onSubmit={submit} noValidate>
          {!confirming && (
            <>
              <div className="field">
                <label htmlFor="email">Email</label>
                <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="password">Password</label>
                <input id="password" type="password" required minLength={10}
                       autoComplete={mode === "login" ? "current-password" : "new-password"}
                       aria-describedby={mode === "signup" ? "pw-hint" : undefined}
                       value={password} onChange={(e) => setPassword(e.target.value)} />
                {mode === "signup" && <span id="pw-hint" className="hint">At least 10 characters, with upper and lower case and a number.</span>}
              </div>
            </>
          )}
          {confirming && (
            <div className="field">
              <label htmlFor="code">Confirmation code</label>
              <input id="code" inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required
                     value={code} onChange={(e) => setCode(e.target.value)} />
            </div>
          )}
          <p className="form-error" role="alert" aria-live="assertive">{error}</p>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "One moment…" : mode === "login" ? "Sign in" : confirming ? "Confirm and sign in" : "Create account"}
          </button>
        </form>
        <p className="auth-alt">
          {mode === "login" ? <>New here? <Link href="/signup">Create an account</Link></> : <>Already have an account? <Link href="/login">Sign in</Link></>}
        </p>
      </div>
    </div>
  );
}
