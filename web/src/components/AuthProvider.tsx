"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { api, ApiError, clearToken, exitDemo, getToken, isDemo } from "@/lib/api";
import type { User } from "@/lib/api-types";
import { useAction } from "@/lib/hooks";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { DemoWelcomeModal } from "@/components/DemoWelcomeModal";

interface AuthCtx {
  /** The signed-in user - non-null everywhere inside the provider. */
  me: User;
  /** Re-fetch /me (e.g. after toggling outbound or connecting an integration). */
  refresh: () => Promise<void>;
  /** Clear token, tear down the WS connection, and return to /login. */
  signOut: () => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/**
 * Wraps the authenticated (app) route group: loads the current user, redirects
 * to /login when there is no (valid) token, and renders a brand splash until
 * the user is known - protected content never flashes unauthenticated.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<User | null>(null);
  const [waking, setWaking] = useState(false);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Named function expression so the retry can self-reference without TDZ.
  const refresh = useCallback(async function refresh(): Promise<void> {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    try {
      setMe(await api.me());
      setWaking(false);
    } catch (e) {
      // Only a client-side rejection invalidates the session: 401 already
      // cleared the token and redirected inside api.ts; a 403/404 from /me
      // means the session itself is broken. A 5xx — e.g. Render's proxy while
      // the free instance cold-boots — is the server's problem, not the
      // session's, and a network failure (uvicorn --reload mid-restart) is
      // transient: for both, keep the token, keep any stale `me`, and retry
      // until the server is back.
      if (e instanceof ApiError && e.status < 500) {
        clearToken();
        router.replace("/login");
      } else {
        setWaking(true);
        retryTimer.current = setTimeout(() => void refresh(), 3000);
      }
    }
  }, [router]);

  const signOut = useCallback(() => {
    // Demo mode has no server session — just clear the demo flag/token locally.
    if (isDemo()) {
      exitDemo();
      setMe(null);
      router.replace("/login");
      return;
    }
    // Best-effort server-side revocation; never block the redirect on it
    // (offline / already-expired tokens just fail silently).
    void api.logout().catch(() => {});
    clearToken();
    setMe(null);
    router.replace("/login");
  }, [router]);

  useEffect(() => {
    // setState happens only inside the promise callback (refresh awaits /me),
    // never synchronously in the effect body.
    queueMicrotask(() => void refresh());
    return () => {
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
  }, [refresh]);

  if (!me) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-cream">
        <Image
          src="/brand/emblem.png"
          alt="SynthSales"
          width={742}
          height={894}
          sizes="64px"
          priority
          className="h-16 w-auto animate-pulse motion-reduce:animate-none"
        />
        {waking && (
          <p className="text-sm text-ink-soft">
            Waking the server — this can take up to a minute&hellip;
          </p>
        )}
      </div>
    );
  }

  return (
    <Ctx.Provider value={{ me, refresh, signOut }}>
      {children}
      <AccessRequiredModal />
      <DemoWelcomeModal />
    </Ctx.Provider>
  );
}

/**
 * Global "Request access" prompt, shown center-screen whenever a gated action
 * returns the access-required 403. `api.ts` dispatches the `access-required`
 * window event; this listens and offers the request right there (other toasts
 * are unaffected). Must live inside the provider so it can read `me`.
 */
function AccessRequiredModal() {
  const { me, refresh } = useAuth();
  const { busy, run } = useAction();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onEvt = () => setOpen(true);
    window.addEventListener("access-required", onEvt);
    return () => window.removeEventListener("access-required", onEvt);
  }, []);

  if (!open) return null;
  const pending = me.access_status === "pending";

  const request = () =>
    void run(
      "request-access",
      async () => {
        await api.requestAccess();
        await refresh();
        return true;
      },
      { success: "Access requested — an admin will review it." },
    ).then((ok) => {
      if (ok) setOpen(false);
    });

  return (
    <Modal open onClose={() => setOpen(false)} title="Access required">
      <p className="text-sm text-ink-soft">
        {pending
          ? "Your access request is pending review. An admin will enable outreach and outbound sending for your account."
          : "Outreach and outbound sending need admin approval — research and contact-finding stay available. Request access and an admin will review it."}
      </p>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={() => setOpen(false)}>
          {pending ? "Close" : "Not now"}
        </Button>
        {!pending && (
          <Button busy={busy === "request-access"} onClick={request}>
            Request access
          </Button>
        )}
      </div>
    </Modal>
  );
}
