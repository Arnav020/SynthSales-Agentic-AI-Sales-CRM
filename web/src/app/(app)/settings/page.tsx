"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CalendarClock, Inbox, type LucideIcon } from "lucide-react";
import { api } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { useAuth } from "@/components/AuthProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, Input } from "@/components/ui/Field";
import { ErrorCard } from "@/components/ui/ErrorCard";
import { ConfirmModal } from "@/components/ui/Modal";
import { SkeletonRows } from "@/components/ui/Skeleton";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";

const TAB_VALUES = ["profile", "sending", "connections"] as const;
type Tab = (typeof TAB_VALUES)[number];

const TAB_ITEMS = [
  { value: "profile", label: "Profile" },
  { value: "sending", label: "Sending" },
  { value: "connections", label: "Connections" },
];

// ---- local components ------------------------------------------------------

// Same switch idiom as the agents page: a real role="switch" button.
function Switch({
  checked,
  busy,
  label: name,
  onToggle,
}: {
  checked: boolean;
  busy: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={name}
      aria-busy={busy}
      disabled={busy}
      onClick={onToggle}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition disabled:pointer-events-none disabled:opacity-50 ${
        checked ? "bg-moss" : "bg-ink/20"
      }`}
    >
      <span
        aria-hidden
        className={`size-3.5 rounded-full bg-cream transition-transform ${
          checked ? "translate-x-[18px]" : "translate-x-1"
        }`}
      />
    </button>
  );
}

function ProfileRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-2.5">
      <dt className="text-sm text-ink-soft">{label}</dt>
      <dd className="text-sm font-medium text-ink">{value}</dd>
    </div>
  );
}

function ConnectionCard({
  icon: Icon,
  name,
  connected,
  line,
  busy,
  onConnect,
  onRequestDisconnect,
  upcoming = false,
}: {
  icon: LucideIcon;
  name: string;
  connected: boolean;
  line: string;
  busy: boolean;
  onConnect: () => void;
  onRequestDisconnect: () => void;
  upcoming?: boolean;
}) {
  return (
    <section className="rounded-2xl border border-line bg-paper p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-ink/5 text-ink-soft">
            <Icon size={16} strokeWidth={1.75} aria-hidden />
          </span>
          <p className="truncate font-medium text-ink">{name}</p>
        </div>
        <Badge tone={upcoming ? "amber" : connected ? "moss" : "faint"}>
          {upcoming ? "Upcoming" : connected ? "Connected" : "Not connected"}
        </Badge>
      </div>
      <p className="mt-3 text-sm text-ink-soft">{line}</p>
      <div className="mt-4">
        {upcoming ? (
          <Button variant="secondary" disabled>
            Coming soon
          </Button>
        ) : connected ? (
          <Button variant="secondary" busy={busy} onClick={onRequestDisconnect}>
            Disconnect
          </Button>
        ) : (
          <Button busy={busy} onClick={onConnect}>
            Connect Google
          </Button>
        )}
      </div>
    </section>
  );
}

// Shown on the Sending tab when the account isn't access-approved: explains the
// restriction and lets the user request (or re-request) access.
function AccessGate({
  status,
  reason,
  busy,
  onRequest,
}: {
  status: "none" | "pending" | "approved" | "rejected";
  reason: string | null;
  busy: boolean;
  onRequest: () => void;
}) {
  if (status === "pending") {
    return (
      <Card title="Outbound email">
        <p className="text-sm text-ink-soft">
          Your access request is{" "}
          <strong className="font-medium text-ink">pending review</strong>. An admin will enable the
          outreach agents and outbound sending for your account.
        </p>
      </Card>
    );
  }
  return (
    <Card title="Outbound email">
      <p className="text-sm text-ink-soft">
        {status === "rejected"
          ? "Your access request was declined."
          : "Outbound sending and the outreach agents are restricted for new accounts to prevent abuse."}
      </p>
      {status === "rejected" && reason && (
        <p className="mt-2 rounded-lg bg-cream px-3 py-2 text-sm text-ink-soft">
          <span className="font-medium text-ink">Reason:</span> {reason}
        </p>
      )}
      <p className="mt-3 text-sm text-ink-soft">
        Request access to enable outreach drafting and real email sending. Research and
        contact-finding stay available either way.
      </p>
      <div className="mt-4">
        <Button busy={busy} onClick={onRequest}>
          {status === "rejected" ? "Request again" : "Request access"}
        </Button>
      </div>
    </Card>
  );
}

// ---- page ------------------------------------------------------------------

function SettingsInner() {
  const router = useRouter();
  const search = useSearchParams();
  const { me, refresh } = useAuth();
  const { toast } = useToast();
  const { busy, run } = useAction();

  const health = useApi(api.health);
  const providers = useApi(api.authProviders);

  const [confirmEnable, setConfirmEnable] = useState(false);
  const [confirmAuto, setConfirmAuto] = useState(false);
  const [disconnecting, setDisconnecting] = useState<"calendar" | "mailbox" | null>(null);
  const [name, setName] = useState(me.name);
  const [companyName, setCompanyName] = useState(me.company_name);

  // ---- tab ↔ URL (one-directional, like the campaign filter chips) ----------
  const rawTab = search.get("tab");
  // A fresh OAuth redirect (?calendar=… / ?mailbox=…) carries no tab param but
  // belongs on Connections - infer it so the right tab shows before the URL is
  // cleaned up below.
  const cbParam = search.get("calendar") ?? search.get("mailbox");
  const tab: Tab = (TAB_VALUES as readonly string[]).includes(rawTab ?? "")
    ? (rawTab as Tab)
    : cbParam
      ? "connections"
      : "profile";

  // ---- Google OAuth callback params (once-only, the oauth-callback pattern) --
  // Backend redirects: /settings?calendar=connected|denied|state|exchange and
  // /settings?mailbox=… (auth.py google_calendar_callback / google_mailbox_callback).
  const handledCb = useRef(false);
  useEffect(() => {
    const cal = search.get("calendar");
    const mail = search.get("mailbox");
    if ((!cal && !mail) || handledCb.current) return;
    handledCb.current = true;
    const what = cal ? "Google Calendar" : "Mailbox";
    const code = cal ?? mail;
    if (code === "connected") {
      toast(`${what} connected`, "success");
      void refresh();
    } else if (code === "denied") {
      toast("You declined the Google consent screen.", "error");
    } else {
      // state (expired/forged state, missing code, unknown user) or exchange
      // (no refresh token from Google) - both mean "start the flow over".
      toast("Connection failed. Try again.", "error");
    }
    router.replace("/settings?tab=connections");
  }, [search, refresh, router, toast]);

  // ---- sending (the outbound kill-switch) ------------------------------------
  // Busy covers the PATCH *and* the /me refresh so the switch can't be
  // re-toggled while the topbar chip is still catching up.
  const setOutbound = (enabled: boolean) =>
    run(
      "outbound",
      async () => {
        await api.setOutbound(enabled);
        await refresh();
        return true;
      },
      {
        success: enabled
          ? "Real sending is on"
          : "Sending paused: nothing reaches a prospect",
      },
    );

  const setAutonomous = (enabled: boolean) =>
    run(
      "autonomous",
      async () => {
        await api.setAutonomousReplies(enabled);
        await refresh();
        return true;
      },
      { success: enabled ? "Autonomous replies on" : "Autonomous replies off" },
    );

  const hasAccess = me.is_admin || me.access_status === "approved";
  const requestAccess = () =>
    run(
      "request-access",
      async () => {
        await api.requestAccess();
        await refresh();
        return true;
      },
      { success: "Access requested — an admin will review it." },
    );

  // ---- connections -----------------------------------------------------------
  const connect = (key: "calendar" | "mailbox") =>
    void run(
      `connect:${key}`,
      key === "calendar" ? api.connectCalendar : api.connectMailbox,
      // Full-page navigation to Google's consent screen; we leave the app here.
      { onDone: (r) => window.location.assign(r.url) },
    );

  // ---- profile (name + company; email stays immutable) -----------------------
  const trimmedName = name.trim();
  const trimmedCompany = companyName.trim();
  const nameDirty = trimmedName !== "" && trimmedName !== me.name;
  // Unlike the name, clearing the company is legal — drafts fall back to "we".
  const companyDirty = trimmedCompany !== me.company_name;
  const profileDirty = nameDirty || companyDirty;
  const saveProfile = () =>
    run(
      "profile",
      async () => {
        await api.updateProfile({
          ...(nameDirty ? { name: trimmedName } : {}),
          ...(companyDirty ? { company_name: trimmedCompany } : {}),
        });
        await refresh();
        return true;
      },
      { success: "Profile updated" },
    );

  const memberSince = new Date(me.created_at).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });

  const emailMode = health.data?.integrations.email_mode ?? null;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="space-y-4">
        <h1 className="display text-3xl sm:text-4xl">Settings</h1>
        <Tabs
          value={tab}
          onChange={(v) => router.replace(`/settings?tab=${v}`)}
          items={TAB_ITEMS}
        />
      </header>

      {tab === "profile" && (
        <>
          <Card title="Profile">
            <div className="space-y-4">
              <Field label="Name" htmlFor="profile-name">
                <Input
                  id="profile-name"
                  value={name}
                  maxLength={120}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <Field label="Company" htmlFor="profile-company">
                <Input
                  id="profile-company"
                  value={companyName}
                  maxLength={200}
                  placeholder="e.g. Apex Cloud"
                  onChange={(e) => setCompanyName(e.target.value)}
                />
                <p className="mt-1.5 text-sm text-ink-soft">
                  Your company&apos;s name — AI-written outreach and replies use it
                  as the sender (&ldquo;At {trimmedCompany || "your company"}, we
                  help&hellip;&rdquo;). Leave blank to stay anonymous
                  (&ldquo;we&rdquo;).
                </p>
              </Field>
              <dl className="divide-y divide-line border-t border-line">
                <ProfileRow label="Email" value={me.email} />
                <ProfileRow label="Member since" value={memberSince} />
              </dl>
              <div className="flex justify-end">
                <Button
                  busy={busy === "profile"}
                  disabled={!profileDirty}
                  onClick={() => void saveProfile()}
                >
                  Save changes
                </Button>
              </div>
            </div>
          </Card>

          <Card title="Reset password">
            <p className="text-sm text-ink-soft">We&apos;ll email you a code.</p>
            <Link
              href="/forgot-password"
              className="mt-3 inline-block text-sm font-medium text-terracotta hover:underline"
            >
              Reset password →
            </Link>
          </Card>
        </>
      )}

      {tab === "sending" &&
        (hasAccess ? (
        <Card title="Outbound email">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="font-medium text-ink">
                Real email sending is {me.outbound_enabled ? "on" : "paused"}
              </p>
              <p className="mt-1 text-sm text-ink-soft">
                {me.outbound_enabled
                  ? "Real email will be delivered to prospects on send and follow-up."
                  : "No real email reaches a prospect while paused. Test sends to yourself always work."}
              </p>
            </div>
            <div className="pt-1">
              <Switch
                checked={me.outbound_enabled}
                busy={busy === "outbound"}
                label="Real email sending"
                onToggle={() =>
                  // Pausing is the safe direction - instant. Enabling warns first.
                  me.outbound_enabled
                    ? void setOutbound(false)
                    : setConfirmEnable(true)
                }
              />
            </div>
          </div>

          <div className="mt-4 flex items-start justify-between gap-4 border-t border-line pt-4">
            <div className="min-w-0">
              <p className="font-medium text-ink">
                Autonomous replies are {me.autonomous_replies ? "on" : "off"}
              </p>
              <p className="mt-1 text-sm text-ink-soft">
                {me.autonomous_replies
                  ? "High-confidence replies are answered automatically: interested books a meeting + sends the link, not-interested gets a closing note, answerable questions are answered."
                  : "Replies are only surfaced for you to handle. Requires real sending to be on."}
              </p>
            </div>
            <div className="pt-1">
              <Switch
                checked={me.autonomous_replies}
                busy={busy === "autonomous"}
                label="Autonomous replies"
                onToggle={() =>
                  me.autonomous_replies
                    ? void setAutonomous(false)
                    : setConfirmAuto(true)
                }
              />
            </div>
          </div>

          {emailMode && (
            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-4 text-sm text-ink-soft">
              <Badge tone={emailMode === "console" ? "amber" : "moss"}>
                {emailMode}
              </Badge>
              <span>
                {emailMode === "console"
                  ? "The email provider is in console mode: messages are only logged on the backend, so nothing is delivered even while sending is on."
                  : emailMode === "gmail"
                    ? "Outbound mail is delivered through the Gmail API."
                    : "Outbound mail is delivered through SMTP."}
              </span>
            </div>
          )}
        </Card>
        ) : (
          <AccessGate
            status={me.access_status}
            reason={me.access_review_note}
            busy={busy === "request-access"}
            onRequest={() => void requestAccess()}
          />
        ))}

      {tab === "connections" &&
        (providers.loading ? (
          <SkeletonRows n={2} />
        ) : providers.error ? (
          <ErrorCard message={providers.error} onRetry={providers.reload} />
        ) : providers.data?.google ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <ConnectionCard
              icon={CalendarClock}
              name="Google Calendar"
              connected={me.calendar_connected}
              line={
                me.calendar_connected
                  ? "Booked meetings create real Calendar events with Google Meet links."
                  : "Connect so booking a meeting creates a real Calendar event with a Meet link."
              }
              busy={busy === "connect:calendar"}
              onConnect={() => connect("calendar")}
              onRequestDisconnect={() => setDisconnecting("calendar")}
            />
            <ConnectionCard
              icon={Inbox}
              name="Mailbox"
              connected={me.mailbox_connected}
              line="Connecting your own mailbox for reply reading is coming soon. For now, replies are read from the shared sending mailbox."
              busy={busy === "connect:mailbox"}
              onConnect={() => connect("mailbox")}
              onRequestDisconnect={() => setDisconnecting("mailbox")}
              upcoming
            />
          </div>
        ) : (
          <Card>
            <p className="text-sm text-ink-soft">
              Google integrations are not configured on this server.
            </p>
          </Card>
        ))}

      {/* Enabling real sending is the dangerous direction - confirm first.
          Failure keeps the modal open (useAction toasts, we re-throw). */}
      <ConfirmModal
        open={confirmEnable}
        onClose={() => setConfirmEnable(false)}
        title="Turn on real sending?"
        body={
          <p>
            Emails will actually reach prospects: outreach sends, automatic
            follow-ups, and meeting invites all go out for real. You can pause
            again at any time.
          </p>
        }
        confirmLabel="Turn on sending"
        onConfirm={async () => {
          const r = await setOutbound(true);
          if (r === null) throw new Error("enable failed");
        }}
      />

      <ConfirmModal
        open={confirmAuto}
        onClose={() => setConfirmAuto(false)}
        title="Turn on autonomous replies?"
        body={
          <p>
            The agent will reply to prospects on its own, booking meetings, sending
            Meet links, answering questions, and sending closing notes, without asking
            first. It only acts on high-confidence replies and still respects the
            outbound switch and do-not-contact. You can turn this off anytime.
          </p>
        }
        confirmLabel="Turn on autonomous replies"
        onConfirm={async () => {
          const r = await setAutonomous(true);
          if (r === null) throw new Error("enable failed");
        }}
      />

      <ConfirmModal
        open={disconnecting !== null}
        onClose={() => setDisconnecting(null)}
        title={
          disconnecting === "mailbox"
            ? "Disconnect mailbox?"
            : "Disconnect Google Calendar?"
        }
        body={
          <p>
            {disconnecting === "mailbox"
              ? "The Reply reader will stop ingesting prospect replies."
              : "Booking will need a pasted meeting link."}
          </p>
        }
        confirmLabel="Disconnect"
        destructive
        onConfirm={async () => {
          if (!disconnecting) return;
          const key = disconnecting;
          const r = await run(
            `disconnect:${key}`,
            async () => {
              await (key === "calendar"
                ? api.disconnectCalendar()
                : api.disconnectMailbox());
              await refresh();
              return true;
            },
            {
              success:
                key === "calendar"
                  ? "Google Calendar disconnected"
                  : "Mailbox disconnected",
            },
          );
          if (r === null) throw new Error("disconnect failed");
        }}
      />
    </div>
  );
}

export default function SettingsPage() {
  // Next 16: useSearchParams must sit under a Suspense boundary.
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-4xl">
          <SkeletonRows n={4} />
        </div>
      }
    >
      <SettingsInner />
    </Suspense>
  );
}
