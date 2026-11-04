"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { safeNext } from "@/lib/format";
import styles from "./SignIn.module.css";

export function SignIn() {
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [why, setWhy] = useState("");
  const [google, setGoogle] = useState(false);
  const next = safeNext(params.get("next"));

  useEffect(() => {
    api
      .providers()
      .then((p) => setGoogle(p.google))
      .catch(() => setGoogle(false));
    try {
      sessionStorage.setItem("ll-next", next);
    } catch {
      // fine: they land on the home page instead
    }
  }, [next]);

  return (
    <main className={styles.page}>
      <section className={styles.card}>
        <p className="label">Sign in</p>
        <h1 className="display">Keep notes, upload lectures, study.</h1>
        {params.get("error") === "google" && (
          <p className={styles.error} role="alert">
            Google sign-in didn&apos;t work. Try again, or use an email link.
          </p>
        )}
        {state === "sent" ? (
          <div className={styles.sent} role="status">
            <strong>Check your email.</strong> We sent a sign-in link to {email}. It works once and
            expires in 15 minutes.
            <button type="button" onClick={() => setState("idle")}>
              Use a different address
            </button>
          </div>
        ) : (
          <form
            className={styles.form}
            onSubmit={async (e) => {
              e.preventDefault();
              setState("sending");
              try {
                await api.emailLink(email);
                setState("sent");
              } catch (err) {
                // the rate limit message is worth showing; anything else gets the generic one
                setWhy(err instanceof ApiError && err.status === 429 ? err.message : "");
                setState("error");
              }
            }}
          >
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@school.edu"
            />
            {state === "error" && (
              <p className={styles.error} role="alert">
                {why || "Couldn't send the link. Check the address and try again."}
              </p>
            )}
            <button type="submit" className={styles.primary} disabled={state === "sending"}>
              {state === "sending" ? "Sending…" : "Email me a sign-in link"}
            </button>
          </form>
        )}
        {google && (
          <a className={styles.google} href="/api/auth/google/start">
            Continue with Google
          </a>
        )}
        <p className={styles.small}>
          No password to remember. <Link href="/search">Search works without an account.</Link>
        </p>
      </section>
    </main>
  );
}

export function VerifyLink() {
  const params = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const once = useRef(false);

  useEffect(() => {
    // strict mode runs effects twice in dev; the token only works once
    if (once.current) return;
    once.current = true;
    const token = params.get("token");
    if (!token) {
      setError("This link is missing its token.");
      return;
    }
    api
      .verify(token)
      .then(() => {
        let next = "/";
        try {
          next = safeNext(sessionStorage.getItem("ll-next"));
        } catch {}
        router.replace(next);
        router.refresh();
      })
      .catch((e: Error) => setError(e.message));
  }, [params, router]);

  return (
    <main className={styles.page}>
      <section className={styles.card} aria-live="polite">
        {error ? (
          <>
            <p className="label">Sign-in link</p>
            <h1 className="display">That link didn&apos;t work.</h1>
            <p className={styles.error}>{error}</p>
            <Link href="/signin" className={styles.primary}>
              Get a new link
            </Link>
          </>
        ) : (
          <>
            <p className="label">Sign-in link</p>
            <h1 className="display">Signing you in…</h1>
          </>
        )}
      </section>
    </main>
  );
}
