// Types mirroring the FastAPI backend response schemas (snake_case).

export type CampaignStatus = "Draft" | "Running" | "Paused" | "Completed" | "Failed";
export type CompanyStatus =
  | "Researching"
  | "Reviewed"
  | "Qualified"
  | "Approved"
  | "Excluded"
  | "Contacted";
export type MatchLevel = "Strong" | "Good" | "Moderate" | "Weak";
export type VerificationStatus = "Verified" | "Risky" | "Invalid" | "Unknown";
export type EmailState = "Queued" | "Sent" | "Delivered" | "Failed";
export type MeetingStatus = "Upcoming" | "Completed" | "Cancelled" | "No-show";
export type ThreadStage =
  | "Contacted"
  | "Replied"
  | "Negotiating"
  | "Meeting"
  | "Closed"
  | "Stalled";
export type NotificationType =
  | "reply"
  | "meeting"
  | "verification"
  | "campaign"
  | "followup"
  | "error";
export type Intent =
  | "interested"
  | "meeting_ready"
  | "not_interested"
  | "question"
  | "out_of_office"
  | "other";

export interface User {
  id: number;
  name: string;
  /** The user's own company — sender identity in AI-written emails ("" = unset). */
  company_name: string;
  email: string;
  is_verified: boolean;
  is_admin: boolean;
  outbound_enabled: boolean;
  autonomous_replies: boolean;
  calendar_connected: boolean;
  mailbox_connected: boolean;
  access_status: "none" | "pending" | "approved" | "rejected";
  access_review_note: string | null;
  created_at: string;
}

/** Mirrors backend schemas.CampaignCreate (= CampaignBase) exactly. */
export interface CampaignCreate {
  name: string;
  product: string;
  tone: string;
  top_n: number;
  product_description: string;
  value_proposition: string;
  industry: string;
  differentiators: string;
  icp: string;
  industry_pref: string;
  geography: string;
  company_size: string;
  business_requirements: string;
  ranking_criteria: string;
  email_template: string;
  footer: string;
  personalization_level: number;
}

export interface Campaign {
  id: number;
  name: string;
  product: string;
  status: "Draft" | "Running" | "Paused" | "Completed" | "Failed";
  tone: string;
  top_n: number;
  created_at: string;
  companies_uploaded: number;
  companies_researched: number;
  emails_sent: number;
  replies_received: number;
  meetings_booked: number;
}

export interface ScoreFactor {
  label: string;
  weight: number;
  score: number;
}

export interface Company {
  id: number;
  campaign_id: number;
  name: string;
  domain: string;
  mail_domain: string;
  industry: string;
  size: string;
  location: string;
  ai_score: number;
  rank: number;
  match_level: "Strong" | "Good" | "Moderate" | "Weak";
  status: CompanyStatus;
  research_summary: string;
  research_points: string[];
  match_explanation: string;
  score_factors: ScoreFactor[];
  recent_funding?: string | null;
  recent_news?: string | null;
  active_hiring: boolean;
  enrichment_confidence: number;
  domain_status: "live" | "parked" | "dead" | "unknown";
  contacts_found: number;
  contacts_verified: number;
}

export interface Contact {
  id: number;
  company_id: number;
  name: string;
  role: string;
  email: string;
  linkedin?: string | null;
  verification: "Verified" | "Risky" | "Invalid" | "Unknown";
  confidence: number;
  approved: boolean | null;
  do_not_contact: boolean;
}

export interface ContactCreate {
  name: string;
  role?: string;
  email?: string;
  linkedin?: string | null;
}

export interface CompanyDetail extends Company {
  contacts: Contact[];
}

export interface EmailDraft {
  id: number;
  contact_id: number;
  subject: string;
  body: string;
  footer: string;
  state: "Queued" | "Sent" | "Delivered" | "Failed";
}

export interface ThreadMessage {
  id: number;
  direction: "us" | "them";
  author: string;
  subject?: string | null;
  body: string;
  is_follow_up: boolean;
  intent?: Intent | null;
  sent_at: string;
}

export interface Thread {
  id: number;
  campaign_id: number;
  company_id?: number | null;
  contact_id?: number | null;
  subject: string;
  stage: ThreadStage;
  unread: boolean;
  last_activity: string;
  company_name: string;
  contact_name: string;
  role: string;
  email: string;
  last_intent?: Intent | null;
}

export interface ThreadDetail extends Thread {
  messages: ThreadMessage[];
  ai_suggestion?: string | null;
}

export interface Meeting {
  id: number;
  campaign_id?: number | null;
  company: string;
  contact: string;
  scheduled_at: string;
  status: "Upcoming" | "Completed" | "Cancelled" | "No-show";
  link: string;
  notes?: string | null;
}

export interface AppNotification {
  id: number;
  type: "reply" | "meeting" | "verification" | "campaign" | "followup" | "error";
  title: string;
  detail: string;
  read: boolean;
  created_at: string;
}

export interface LogEntry {
  id: number;
  category: "Campaign" | "Email" | "AI" | "Verification" | "User";
  level: "info" | "warn" | "error";
  message: string;
  created_at: string;
}

export interface Agent {
  id: number;
  key: string;
  name: string;
  description: string;
  enabled: boolean;
  order: number;
  status: "Idle" | "Running" | "Error";
  last_run?: string | null;
}

export interface PipelineAgent {
  key: string;
  name: string;
  description: string;
  order: number;
  status: "Idle" | "Running" | "Error";
  enabled: boolean;
  last_run?: string | null;
  total: number;
  completed: number;
  runnable: boolean;
}

export interface SnapshotStatus {
  available: boolean;
  reason?: string | null;   // "conversation_active" | "none"
  trigger?: string | null;  // "pipeline" | "agent:<key>"
  label?: string | null;    // e.g. "Full pipeline run" | "Re-run: Company Scoring"
  created_at?: string | null;
  expires_at?: string | null;
}

export interface FunnelStage {
  label: string;
  value: number;
}

export interface Dashboard {
  active_campaigns: number;
  paused_campaigns: number;
  completed_campaigns: number;
  companies_uploaded: number;
  companies_researched: number;
  emails_sent: number;
  replies_received: number;
  meetings_booked: number;
  funnel: FunnelStage[];
}

export interface Token {
  access_token: string;
  token_type: string;
}

export interface RegisterResponse extends User {
  dev_otp?: string | null;
  email_sent: boolean;
}

export interface ResendResponse {
  detail: string;
  email_sent: boolean;
  dev_otp?: string | null;
}

export interface AuthProviders {
  google: boolean;
}

export interface ForgotPasswordResponse {
  detail: string;
  email_sent: boolean;
  dev_otp?: string | null;
}

// ---- conversations sync ----

export interface SyncResult {
  ingested: number;
  classified: number;
}

// ---- system health ----

export interface HealthOut {
  status: string;
  app: string;
  integrations: {
    ai: boolean;
    search: string;
    email_verification: string;
    email_finder: string;
    email_mode: string;
    google_oauth: boolean;
  };
}

// ---- admin (cross-tenant) ----

export interface AdminUserRow {
  id: number;
  name: string;
  email: string;
  is_verified: boolean;
  outbound_enabled: boolean;
  is_admin: boolean;
  access_status: string;
  campaigns: number;
  companies: number;
  contacts: number;
}

export interface AccessRequestRow {
  id: number;
  name: string;
  email: string;
  note: string | null;
  requested_at: string | null;
}

export interface AdminCampaignRow {
  id: number;
  owner_id: number;
  name: string;
  status: string;
  top_n: number;
  companies: number;
  contacts: number;
  drafts: number;
}

// Shape of GET /api/admin/users/{id} (admin.py::get_user_tree).
export interface AdminUserTreeContact {
  id: number;
  name: string;
  role: string;
  email: string;
  verification: string;
  approved: boolean | null;
}

export interface AdminUserTreeCompany {
  id: number;
  name: string;
  rank: number;
  ai_score: number;
  status: string;
  domain_status: string;
  contacts: AdminUserTreeContact[];
}

export interface AdminUserTreeCampaign {
  id: number;
  name: string;
  status: string;
  top_n: number;
  companies: AdminUserTreeCompany[];
}

export interface AdminUserTree {
  user: {
    id: number;
    name: string;
    email: string;
    is_verified: boolean;
    outbound_enabled: boolean;
    is_admin: boolean;
  };
  campaigns: AdminUserTreeCampaign[];
}

// Shape of GET /api/admin/campaigns/{id} (admin.py::get_campaign_tree).
export interface AdminCampaignDetailDraft {
  id: number;
  subject: string;
  state: string;
}

export interface AdminCampaignDetailContact {
  id: number;
  name: string;
  role: string;
  email: string;
  linkedin: string | null;
  verification: string;
  confidence: number;
  approved: boolean | null;
  drafts: AdminCampaignDetailDraft[];
}

export interface AdminCampaignDetailCompany {
  id: number;
  name: string;
  domain: string;
  industry: string;
  size: string;
  location: string;
  rank: number;
  ai_score: number;
  match_level: string;
  status: string;
  enrichment_confidence: number;
  metric_confidence: number;
  domain_status: string;
  research_summary: string;
  research_points: string[];
  match_explanation: string;
  score_factors: ScoreFactor[];
  recent_funding: string | null;
  recent_news: string | null;
  active_hiring: boolean;
  contacts: AdminCampaignDetailContact[];
}

export interface AdminCampaignDetail {
  campaign: {
    id: number;
    owner_id: number;
    owner_email: string | null;
    name: string;
    product: string;
    status: string;
    tone: string;
    top_n: number;
    icp: string;
    industry_pref: string;
    geography: string;
    company_size: string;
    business_requirements: string;
    ranking_criteria: string;
  };
  companies: AdminCampaignDetailCompany[];
}
