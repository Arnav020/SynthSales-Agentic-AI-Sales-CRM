// Static dummy data for the read-only demo account. Everything the app reads in
// demo mode resolves from here — no network call ever leaves the browser. Shapes
// mirror `api-types.ts` (and the backend seed in `services/seed.py`) so the demo
// renders identically to a real seeded account. Nothing here is writable; the
// demo blocks every mutation at the `api.ts` request boundary.

import type {
  Agent,
  AppNotification,
  Campaign,
  Company,
  CompanyDetail,
  Contact,
  Dashboard,
  EmailDraft,
  LogEntry,
  Meeting,
  PipelineAgent,
  SnapshotStatus,
  Thread,
  ThreadDetail,
  User,
} from "./api-types";

const FOOTER =
  "Best,\nAlex Rivera\nAccount Executive, Apex Cloud\nalex@apexcloud.com";

// Meeting dates are computed relative to "now" so the demo always has live
// upcoming meetings, no matter when it's viewed (fixed dates would rot into the
// past). Evaluated once at module load; stable for the session.
function offsetISO(days: number, hourUtc = 16): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + days);
  d.setUTCHours(hourUtc, 0, 0, 0);
  return d.toISOString();
}

export const DEMO_USER: User = {
  id: 9999,
  name: "Alex Rivera",
  company_name: "Apex Cloud",
  email: "demo@synthsales.app",
  is_verified: true,
  is_admin: false,
  outbound_enabled: true,
  autonomous_replies: false,
  calendar_connected: true,
  mailbox_connected: true,
  access_status: "approved",
  access_review_note: null,
  created_at: "2026-04-02T10:00:00Z",
};

const CAMPAIGNS: Campaign[] = [
  { id: 1, name: "Apex Cloud — Q2 Enterprise Push", product: "Apex Cloud Data Platform", status: "Running", tone: "consultative", top_n: 50, created_at: "2026-04-10T09:00:00Z", companies_uploaded: 18, companies_researched: 18, emails_sent: 6, replies_received: 2, meetings_booked: 4 },
  { id: 2, name: "FinTech Mid-Market Expansion", product: "LedgerOne Payments API", status: "Running", tone: "professional", top_n: 40, created_at: "2026-04-22T09:00:00Z", companies_uploaded: 24, companies_researched: 24, emails_sent: 9, replies_received: 3, meetings_booked: 1 },
  { id: 3, name: "HealthOps Pilot Outreach", product: "HealthOps Scheduling Suite", status: "Paused", tone: "friendly", top_n: 30, created_at: "2026-05-01T09:00:00Z", companies_uploaded: 12, companies_researched: 12, emails_sent: 4, replies_received: 1, meetings_booked: 0 },
  { id: 4, name: "Retail Analytics — Spring", product: "ShelfIQ Analytics", status: "Completed", tone: "concise", top_n: 60, created_at: "2026-03-05T09:00:00Z", companies_uploaded: 40, companies_researched: 40, emails_sent: 22, replies_received: 7, meetings_booked: 4 },
  { id: 5, name: "Logistics Net-New", product: "CargoX Route Optimizer", status: "Running", tone: "professional", top_n: 50, created_at: "2026-05-20T09:00:00Z", companies_uploaded: 4, companies_researched: 4, emails_sent: 0, replies_received: 0, meetings_booked: 0 },
];

const FACTOR_LABELS: [string, number][] = [
  ["Product fit", 0.3], ["Industry alignment", 0.2], ["Company relevance", 0.15],
  ["Requirement satisfaction", 0.15], ["Market compatibility", 0.1], ["Growth indicators", 0.1],
];

function factors(score: number) {
  return FACTOR_LABELS.map(([label, weight], i) => ({
    label,
    weight,
    score: Math.max(40, Math.min(99, score + (i - 2) * 3)),
  }));
}

// Compact builder for the secondary campaigns' companies — fills the boilerplate
// (mail_domain = domain, derived score_factors, sensible nulls) from a short spec.
type CompanySpec = {
  id: number; campaign_id: number; name: string; domain: string; industry: string;
  size: string; location: string; ai_score: number; rank: number;
  match_level: Company["match_level"]; status: Company["status"];
  summary: string; points: string[]; explanation: string; hiring: boolean;
  confidence: number; domain_status: Company["domain_status"];
  found: number; verified: number; funding?: string; news?: string;
  // Enriched but not yet scored (campaign stopped after research): no score_factors.
  unscored?: boolean;
};

function mkCompany(c: CompanySpec): Company {
  return {
    id: c.id, campaign_id: c.campaign_id, name: c.name, domain: c.domain,
    mail_domain: c.domain, industry: c.industry, size: c.size, location: c.location,
    ai_score: c.ai_score, rank: c.rank, match_level: c.match_level, status: c.status,
    research_summary: c.summary, research_points: c.points, match_explanation: c.explanation,
    score_factors: c.unscored ? [] : factors(c.ai_score), recent_funding: c.funding ?? null,
    recent_news: c.news ?? null, active_hiring: c.hiring,
    enrichment_confidence: c.confidence, domain_status: c.domain_status,
    contacts_found: c.found, contacts_verified: c.verified,
  };
}

const COMPANIES: Company[] = [
  { id: 1, campaign_id: 1, name: "Northwind Logistics", domain: "northwind.com", mail_domain: "northwind.com", industry: "Logistics & Supply Chain", size: "1,000–5,000", location: "Chicago, US", ai_score: 94, rank: 1, match_level: "Strong", status: "Approved", research_summary: "Mid-large 3PL operator modernizing its data stack after a recent cloud migration; consolidating analytics vendors.", research_points: ["Mid-large 3PL operator running national freight and warehousing.", "Recently completed a cloud migration and is modernizing its data stack.", "Consolidating analytics vendors — active evaluation signals.", "Series D — $120M raised (Feb 2026), funding a data-platform buildout.", "Actively hiring for data engineering and analytics roles."], match_explanation: "High product fit, strong industry alignment, active hiring for data roles.", score_factors: factors(94), recent_funding: "Series D — $120M (Feb 2026)", recent_news: null, active_hiring: true, enrichment_confidence: 92, domain_status: "live", contacts_found: 3, contacts_verified: 2 },
  { id: 2, campaign_id: 1, name: "Brightwave Manufacturing", domain: "brightwave.io", mail_domain: "brightwave.io", industry: "Industrial Manufacturing", size: "500–1,000", location: "Austin, US", ai_score: 88, rank: 2, match_level: "Strong", status: "Approved", research_summary: "Smart-factory manufacturer generating large telemetry volumes; emphasizes predictive maintenance.", research_points: ["Smart-factory manufacturer with heavily instrumented production lines.", "Generates large telemetry volumes from IoT sensors across plants.", "Prioritizing predictive maintenance and real-time analytics.", "Actively hiring for industrial data and ML roles."], match_explanation: "Strong requirement satisfaction around real-time analytics.", score_factors: factors(88), recent_funding: null, recent_news: null, active_hiring: true, enrichment_confidence: 88, domain_status: "live", contacts_found: 2, contacts_verified: 2 },
  { id: 3, campaign_id: 1, name: "Summit Retail Group", domain: "summitretail.com", mail_domain: "summitretail.com", industry: "Retail", size: "5,000+", location: "Seattle, US", ai_score: 79, rank: 3, match_level: "Good", status: "Qualified", research_summary: "National retail chain with a maturing analytics team; recent cost-optimization program.", research_points: ["National retail chain with 5,000+ employees across US stores.", "Analytics team maturing from reporting toward predictive use cases.", "Announced a 5% cost-reduction program (Apr 2026) — budget scrutiny likely."], match_explanation: "Good fit but cost-cutting news lowers timing score.", score_factors: factors(79), recent_funding: null, recent_news: "Announced 5% cost-reduction program (Apr 2026)", active_hiring: false, enrichment_confidence: 74, domain_status: "live", contacts_found: 1, contacts_verified: 0 },
  { id: 4, campaign_id: 1, name: "Vertex Health Systems", domain: "vertexhealth.org", mail_domain: "vertexhealth.org", industry: "Healthcare", size: "1,000–5,000", location: "Boston, US", ai_score: 71, rank: 4, match_level: "Good", status: "Researching", research_summary: "Regional hospital network with strict compliance requirements.", research_points: ["Regional hospital network operating across multiple facilities.", "Strict HIPAA / compliance requirements shape any data tooling.", "Hiring for clinical-data and IT roles."], match_explanation: "Moderate fit; compliance overhead reduces requirement satisfaction.", score_factors: factors(71), recent_funding: null, recent_news: null, active_hiring: true, enrichment_confidence: 64, domain_status: "live", contacts_found: 0, contacts_verified: 0 },
  { id: 5, campaign_id: 1, name: "Orbit Media Holdings", domain: "orbitmedia.tv", mail_domain: "orbitmedia.tv", industry: "Media & Entertainment", size: "200–500", location: "Los Angeles, US", ai_score: 52, rank: 5, match_level: "Weak", status: "Excluded", research_summary: "Smaller media holding company with limited public modernization signals.", research_points: ["Smaller media holding company across TV and digital properties.", "Limited public signals of analytics or modernization investment.", "Reported flat YoY revenue (Q1 2026)."], match_explanation: "Low requirement satisfaction; excluded by reviewer.", score_factors: factors(52), recent_funding: null, recent_news: "Reported flat YoY revenue (Q1 2026)", active_hiring: false, enrichment_confidence: 38, domain_status: "parked", contacts_found: 0, contacts_verified: 0 },

  // ---- Campaign 2: FinTech Mid-Market Expansion (LedgerOne Payments API) ----
  mkCompany({ id: 11, campaign_id: 2, name: "NovaPay Solutions", domain: "novapay.com", industry: "Financial Services", size: "500–1,000", location: "New York, US", ai_score: 91, rank: 1, match_level: "Strong", status: "Approved", summary: "Fast-scaling payments processor expanding into embedded finance; actively evaluating payment APIs.", points: ["Payments processor serving mid-market merchants nationwide.", "Expanding into embedded finance and BNPL.", "Series C — $80M raised (Mar 2026) earmarked for platform.", "Hiring across payments engineering and risk."], explanation: "Excellent product fit and timing — active API evaluation.", hiring: true, confidence: 90, domain_status: "live", found: 2, verified: 2, funding: "Series C — $80M (Mar 2026)" }),
  mkCompany({ id: 12, campaign_id: 2, name: "Cobalt Lending", domain: "cobaltlending.com", industry: "Lending", size: "200–500", location: "Charlotte, US", ai_score: 84, rank: 2, match_level: "Strong", status: "Qualified", summary: "Digital lender modernizing disbursement and repayment rails.", points: ["Consumer + SMB digital lender.", "Replacing legacy ACH flows with modern rails.", "Hiring for payments and platform roles."], explanation: "Strong requirement satisfaction around disbursement APIs.", hiring: true, confidence: 82, domain_status: "live", found: 1, verified: 1 }),
  mkCompany({ id: 13, campaign_id: 2, name: "Harbor Financial", domain: "harborfin.com", industry: "Banking", size: "1,000–5,000", location: "Chicago, US", ai_score: 77, rank: 3, match_level: "Good", status: "Qualified", summary: "Regional bank migrating core banking to the cloud.", points: ["Regional bank with a multi-year cloud migration underway.", "Evaluating modern payment infrastructure.", "Compliance-heavy buying process."], explanation: "Good fit; long procurement cycle tempers timing.", hiring: false, confidence: 73, domain_status: "live", found: 0, verified: 0, news: "Migrating core banking to cloud (2026)" }),
  mkCompany({ id: 14, campaign_id: 2, name: "Meridian Wealth", domain: "meridianwealth.com", industry: "Wealth Management", size: "200–500", location: "Boston, US", ai_score: 68, rank: 4, match_level: "Good", status: "Researching", summary: "Wealth manager digitizing client money movement.", points: ["Boutique wealth manager.", "Digitizing client onboarding and transfers.", "Hiring for digital product roles."], explanation: "Moderate fit; smaller transaction volume.", hiring: true, confidence: 66, domain_status: "live", found: 0, verified: 0 }),
  mkCompany({ id: 15, campaign_id: 2, name: "PaperTrail Inc", domain: "papertrail.io", industry: "Accounting SaaS", size: "50–200", location: "Austin, US", ai_score: 49, rank: 5, match_level: "Weak", status: "Excluded", summary: "Small accounting SaaS with a parked marketing domain.", points: ["Small accounting SaaS vendor.", "Limited public signals of payments investment."], explanation: "Low requirement satisfaction; excluded by reviewer.", hiring: false, confidence: 40, domain_status: "parked", found: 0, verified: 0 }),

  // ---- Campaign 3: HealthOps Pilot Outreach (HealthOps Scheduling Suite) ----
  mkCompany({ id: 21, campaign_id: 3, name: "Cedar Clinics", domain: "cedarclinics.com", industry: "Healthcare", size: "500–1,000", location: "Denver, US", ai_score: 89, rank: 1, match_level: "Strong", status: "Approved", summary: "Multi-site clinic group fighting patient no-shows and scheduling churn.", points: ["Multi-site outpatient clinic group.", "High no-show rates straining capacity.", "Actively evaluating scheduling tooling.", "Hiring for operations and patient-experience roles."], explanation: "Excellent fit — scheduling pain is acute and current.", hiring: true, confidence: 88, domain_status: "live", found: 2, verified: 1 }),
  mkCompany({ id: 22, campaign_id: 3, name: "Lakeside Medical Group", domain: "lakesidemed.org", industry: "Healthcare", size: "1,000–5,000", location: "Minneapolis, US", ai_score: 80, rank: 2, match_level: "Good", status: "Qualified", summary: "Regional medical group standardizing scheduling across facilities.", points: ["Regional medical group across several facilities.", "Standardizing scheduling and intake.", "Hiring clinical-operations roles."], explanation: "Good fit; multi-stakeholder rollout.", hiring: true, confidence: 76, domain_status: "live", found: 1, verified: 0 }),
  mkCompany({ id: 23, campaign_id: 3, name: "BrightSmile Dental", domain: "brightsmile.care", industry: "Dental", size: "200–500", location: "Phoenix, US", ai_score: 72, rank: 3, match_level: "Good", status: "Reviewed", summary: "Growing dental network with manual appointment workflows.", points: ["Dental service organization expanding locations.", "Manual, phone-heavy appointment booking."], explanation: "Reasonable fit; mostly front-desk driven today.", hiring: false, confidence: 70, domain_status: "live", found: 0, verified: 0 }),
  mkCompany({ id: 24, campaign_id: 3, name: "Summit Physio Network", domain: "summitphysio.com", industry: "Physical Therapy", size: "50–200", location: "Salt Lake City, US", ai_score: 58, rank: 4, match_level: "Weak", status: "Researching", summary: "Small physiotherapy network with limited digital infrastructure.", points: ["Small physiotherapy clinic network.", "Limited scheduling-software footprint."], explanation: "Lower fit; small scale and budget.", hiring: false, confidence: 55, domain_status: "live", found: 0, verified: 0 }),

  // ---- Campaign 4: Retail Analytics — Spring (ShelfIQ Analytics) ----
  mkCompany({ id: 31, campaign_id: 4, name: "Harvest Grocers", domain: "harvestgrocers.com", industry: "Grocery Retail", size: "5,000+", location: "Columbus, US", ai_score: 90, rank: 1, match_level: "Strong", status: "Contacted", summary: "National grocery chain investing in shelf-level demand analytics.", points: ["National grocery chain with hundreds of stores.", "Investing in demand forecasting and shrink reduction.", "Actively evaluating analytics vendors.", "Hiring data and merchandising-analytics roles."], explanation: "Excellent fit — analytics budget and active evaluation.", hiring: true, confidence: 89, domain_status: "live", found: 3, verified: 2 }),
  mkCompany({ id: 32, campaign_id: 4, name: "UrbanThreads Apparel", domain: "urbanthreads.com", industry: "Apparel Retail", size: "1,000–5,000", location: "Los Angeles, US", ai_score: 83, rank: 2, match_level: "Strong", status: "Contacted", summary: "Omnichannel apparel retailer optimizing assortment and markdowns.", points: ["Omnichannel apparel retailer.", "Optimizing assortment, markdown and replenishment.", "Hiring retail-analytics roles."], explanation: "Strong requirement satisfaction on assortment analytics.", hiring: true, confidence: 80, domain_status: "live", found: 2, verified: 2 }),
  mkCompany({ id: 33, campaign_id: 4, name: "GreenLeaf Markets", domain: "greenleafmarkets.com", industry: "Organic Retail", size: "500–1,000", location: "Portland, US", ai_score: 75, rank: 3, match_level: "Good", status: "Qualified", summary: "Organic grocery chain modernizing category management.", points: ["Regional organic grocery chain.", "Modernizing category management and pricing."], explanation: "Good fit; mid-size data footprint.", hiring: false, confidence: 72, domain_status: "live", found: 1, verified: 1 }),
  mkCompany({ id: 34, campaign_id: 4, name: "ValueMart Holdings", domain: "valuemart.com", industry: "Discount Retail", size: "5,000+", location: "Dallas, US", ai_score: 66, rank: 4, match_level: "Good", status: "Reviewed", summary: "Discount retailer under margin pressure and store rationalization.", points: ["Large discount retailer.", "Closing underperforming stores — budget scrutiny."], explanation: "Moderate fit; cost-cutting lowers timing score.", hiring: false, confidence: 63, domain_status: "live", found: 0, verified: 0, news: "Closing 30 underperforming stores (2026)" }),
  mkCompany({ id: 35, campaign_id: 4, name: "Coastal Outfitters", domain: "coastaloutfitters.com", industry: "Outdoor Retail", size: "200–500", location: "San Diego, US", ai_score: 51, rank: 5, match_level: "Weak", status: "Excluded", summary: "Smaller outdoor retailer with an unreachable site at scan time.", points: ["Smaller outdoor-gear retailer.", "Domain unreachable during enrichment."], explanation: "Low confidence; excluded by reviewer.", hiring: false, confidence: 44, domain_status: "dead", found: 0, verified: 0 }),

  // ---- Campaign 5: Logistics Net-New (CargoX Route Optimizer) ----
  // Stopped right after research: enriched, NOT yet scored (ai_score 0, no rank,
  // status "Researching") — demonstrates a campaign halted at the first agent.
  mkCompany({ id: 41, campaign_id: 5, name: "FreightLink Carriers", domain: "freightlink.com", industry: "Logistics & Supply Chain", size: "1,000–5,000", location: "Memphis, US", ai_score: 0, rank: 0, match_level: "Moderate", status: "Researching", unscored: true, summary: "Long-haul carrier with public signals of route-inefficiency pressure; enrichment complete, scoring not yet run.", points: ["National long-haul freight carrier.", "Public commentary on rising fuel and empty-mile costs.", "Hiring for logistics-planning roles."], explanation: "Not yet scored — research complete only.", hiring: true, confidence: 70, domain_status: "live", found: 0, verified: 0 }),
  mkCompany({ id: 42, campaign_id: 5, name: "PortSide Logistics", domain: "portside.io", industry: "Freight Forwarding", size: "500–1,000", location: "Long Beach, US", ai_score: 0, rank: 0, match_level: "Moderate", status: "Researching", unscored: true, summary: "Port-adjacent freight forwarder; enrichment complete, scoring pending.", points: ["Freight forwarder near major West Coast ports.", "Coordinates drayage and intermodal moves."], explanation: "Not yet scored — research complete only.", hiring: false, confidence: 66, domain_status: "live", found: 0, verified: 0 }),
  mkCompany({ id: 43, campaign_id: 5, name: "RapidHaul Express", domain: "rapidhaul.com", industry: "Trucking", size: "200–500", location: "Kansas City, US", ai_score: 0, rank: 0, match_level: "Moderate", status: "Researching", unscored: true, summary: "Regional trucking firm; enrichment complete, scoring pending.", points: ["Regional less-than-truckload carrier.", "Manual route planning today."], explanation: "Not yet scored — research complete only.", hiring: false, confidence: 58, domain_status: "live", found: 0, verified: 0 }),
  mkCompany({ id: 44, campaign_id: 5, name: "Meridian Freight Co", domain: "meridianfreight.com", industry: "Logistics & Supply Chain", size: "1,000–5,000", location: "Atlanta, US", ai_score: 0, rank: 0, match_level: "Moderate", status: "Researching", unscored: true, summary: "Freight broker with a parked marketing domain; low enrichment confidence.", points: ["Freight brokerage and 3PL.", "Marketing domain appears parked — limited signals."], explanation: "Not yet scored — research complete only.", hiring: false, confidence: 32, domain_status: "parked", found: 0, verified: 0 }),
];

const CONTACTS: Contact[] = [
  { id: 1, company_id: 1, name: "Dana Whitfield", role: "VP of Data & Analytics", email: "dana.whitfield@northwind.com", linkedin: "linkedin.com/in/danawhitfield", verification: "Verified", confidence: 96, approved: true, do_not_contact: false },
  { id: 2, company_id: 1, name: "Marcus Lee", role: "Director of Engineering", email: "m.lee@northwind.com", linkedin: "linkedin.com/in/marcuslee", verification: "Verified", confidence: 91, approved: true, do_not_contact: false },
  { id: 3, company_id: 1, name: "Priya Nair", role: "Head of Operations", email: "priya.nair@northwind.com", linkedin: "linkedin.com/in/priyanair", verification: "Risky", confidence: 64, approved: null, do_not_contact: false },
  { id: 4, company_id: 2, name: "Tom Schaefer", role: "CTO", email: "tom@brightwave.io", linkedin: "linkedin.com/in/tomschaefer", verification: "Verified", confidence: 93, approved: null, do_not_contact: false },
  { id: 5, company_id: 2, name: "Elena Cortez", role: "VP Operations", email: "e.cortez@brightwave.io", linkedin: "linkedin.com/in/elenacortez", verification: "Verified", confidence: 89, approved: null, do_not_contact: false },
  { id: 6, company_id: 3, name: "Greg Hollis", role: "Director of Analytics", email: "greg.hollis@summitretail.com", linkedin: "linkedin.com/in/greghollis", verification: "Unknown", confidence: 41, approved: null, do_not_contact: true },
];

const DRAFTS: EmailDraft[] = [
  { id: 1, contact_id: 1, state: "Sent", footer: FOOTER, subject: "Unifying Northwind's analytics stack after the cloud migration", body: "Hi Dana,\n\nCongratulations on Northwind's recent cloud migration. As you consolidate analytics vendors, Apex Cloud gives data teams a single platform to model ops data and serve it in real time.\n\nWould a 20-minute walkthrough next week be useful?" },
  { id: 2, contact_id: 4, state: "Queued", footer: FOOTER, subject: "Predictive maintenance telemetry — one platform for Brightwave", body: "Hi Tom,\n\nYour smart-factory push generates exactly the kind of high-volume telemetry that's painful to operationalize. Apex Cloud unifies it so your models get fresh, reliable inputs.\n\nOpen to a short technical demo this week?" },
  { id: 3, contact_id: 5, state: "Queued", footer: FOOTER, subject: "Real-time ops data for Brightwave operations", body: "Hi Elena,\n\nAs Brightwave scales its instrumented lines, your ops team needs trustworthy, real-time data. Apex Cloud unifies it in one place so reporting and alerts stay current.\n\nWorth a quick conversation next week?" },
];

const THREADS: Thread[] = [
  { id: 1, campaign_id: 1, company_id: 1, contact_id: 1, subject: "Unifying Northwind's analytics stack after the cloud migration", stage: "Replied", unread: true, last_activity: "2026-05-27T09:12:00Z", company_name: "Northwind Logistics", contact_name: "Dana Whitfield", role: "VP of Data & Analytics", email: "dana.whitfield@northwind.com", last_intent: "interested" },
  { id: 2, campaign_id: 1, company_id: 2, contact_id: 4, subject: "Predictive maintenance telemetry — one platform for Brightwave", stage: "Negotiating", unread: false, last_activity: "2026-05-26T15:40:00Z", company_name: "Brightwave Manufacturing", contact_name: "Tom Schaefer", role: "CTO", email: "tom@brightwave.io", last_intent: "meeting_ready" },
  { id: 3, campaign_id: 1, company_id: 3, contact_id: 6, subject: "Analytics for Summit Retail's predictive roadmap", stage: "Closed", unread: false, last_activity: "2026-05-20T11:05:00Z", company_name: "Summit Retail Group", contact_name: "Greg Hollis", role: "Director of Analytics", email: "greg.hollis@summitretail.com", last_intent: "not_interested" },
];

const THREAD_DETAILS: Record<number, ThreadDetail> = {
  1: { ...THREADS[0], ai_suggestion: "Thanks Dana — Thursday at 2pm ET or Friday at 11am ET both work on my side. I'll send a calendar invite with a Google Meet link as soon as you confirm.", messages: [
    { id: 1, direction: "us", author: "Alex Rivera", subject: "Unifying Northwind's analytics stack after the cloud migration", body: "Hi Dana, congratulations on Northwind's recent cloud migration. Would a 20-minute walkthrough next week be useful?", is_follow_up: false, intent: null, sent_at: "2026-05-22T10:00:00Z" },
    { id: 2, direction: "them", author: "Dana Whitfield", body: "Hi Alex — timely. We're actively evaluating platforms this quarter. Can you send availability for Thursday or Friday?", is_follow_up: false, intent: "interested", sent_at: "2026-05-27T09:12:00Z" },
  ] },
  2: { ...THREADS[1], ai_suggestion: "Great to hear, Tom. Sharing a Google Meet link for Wednesday 10am CT — I'll tailor the demo to your telemetry pipeline.", messages: [
    { id: 3, direction: "us", author: "Alex Rivera", subject: "Predictive maintenance telemetry — one platform for Brightwave", body: "Hi Tom, your smart-factory push generates exactly the kind of telemetry that's painful to operationalize. Open to a short technical demo this week?", is_follow_up: false, intent: null, sent_at: "2026-05-23T09:30:00Z" },
    { id: 4, direction: "them", author: "Tom Schaefer", body: "This is relevant for us. Let's set up a technical demo — Wednesday morning works. Send a link.", is_follow_up: false, intent: "meeting_ready", sent_at: "2026-05-26T15:40:00Z" },
  ] },
  3: { ...THREADS[2], ai_suggestion: null, messages: [
    { id: 5, direction: "us", author: "Alex Rivera", subject: "Analytics for Summit Retail's predictive roadmap", body: "Hi Greg, as Summit's analytics team matures toward predictive use cases, Apex Cloud could be a fit. Worth a short call?", is_follow_up: false, intent: null, sent_at: "2026-05-15T10:00:00Z" },
    { id: 6, direction: "them", author: "Greg Hollis", body: "Appreciate the note, but our budget is frozen until Q3 and we're not evaluating new tools right now. Please remove me from the list.", is_follow_up: false, intent: "not_interested", sent_at: "2026-05-20T11:05:00Z" },
  ] },
};

const MEETINGS: Meeting[] = [
  { id: 1, campaign_id: 1, company: "Cedar Clinics", contact: "Dr. Amelia Ross", scheduled_at: offsetISO(2, 19), status: "Upcoming", link: "https://meet.google.com/demo-cedar-apex", notes: "Focus on scheduling no-show reduction." },
  { id: 2, campaign_id: 1, company: "Northwind Logistics", contact: "Dana Whitfield", scheduled_at: offsetISO(4, 19), status: "Upcoming", link: "https://meet.google.com/demo-northwind-apex", notes: "Tailor to route + warehouse data." },
  { id: 3, campaign_id: 1, company: "Brightwave Manufacturing", contact: "Tom Schaefer", scheduled_at: offsetISO(9, 16), status: "Upcoming", link: "https://meet.google.com/demo-brightwave-apex", notes: "Technical demo — tailor to their telemetry pipeline and predictive maintenance." },
  { id: 4, campaign_id: 1, company: "Summit Retail Group", contact: "Greg Hollis", scheduled_at: offsetISO(-30, 17), status: "Completed", link: "https://meet.google.com/demo-summit", notes: "Budget frozen until Q3." },
];

const NOTIFICATIONS: AppNotification[] = [
  { id: 1, type: "reply", title: "New reply from Dana Whitfield", detail: "Northwind Logistics — asking for meeting availability.", read: false, created_at: "2026-05-27T09:12:00Z" },
  { id: 2, type: "meeting", title: "Meeting scheduled", detail: "Cedar Clinics — May 29, 3:00 PM ET.", read: false, created_at: "2026-05-26T18:00:00Z" },
  { id: 3, type: "followup", title: "Follow-up sent automatically", detail: "Brightwave — Tom Schaefer (no reply after 24h).", read: true, created_at: "2026-05-25T12:00:00Z" },
  { id: 4, type: "verification", title: "Email verification failed", detail: "Greg Hollis (Summit Retail) returned status: Unknown.", read: true, created_at: "2026-05-24T08:30:00Z" },
];

const LOGS: LogEntry[] = [
  { id: 1, category: "Email", level: "info", message: "Reply detected from dana.whitfield@northwind.com.", created_at: "2026-05-27T09:12:30Z" },
  { id: 2, category: "AI", level: "info", message: "Scoring agent ranked 18 companies for Apex Cloud.", created_at: "2026-05-22T08:00:00Z" },
  { id: 3, category: "Verification", level: "warn", message: "ZeroBounce: greg.hollis@summitretail.com → Unknown.", created_at: "2026-05-24T08:30:00Z" },
  { id: 4, category: "Campaign", level: "info", message: "Enrichment completed for Apex Cloud.", created_at: "2026-05-21T16:00:00Z" },
];

const AGENT_META: { key: string; name: string; description: string }[] = [
  { key: "enrichment", name: "Research", description: "Researches each company's domain, size, funding and signals." },
  { key: "scoring", name: "Scoring & ranking", description: "Scores fit against your ICP and ranks the best targets." },
  { key: "employee_finder", name: "People finder", description: "Finds real decision-makers from public LinkedIn profiles." },
  { key: "email_guess_verification", name: "Email verifier", description: "Guesses and verifies each contact's work email." },
  { key: "outreach", name: "Outreach writer", description: "Drafts a personalized first-touch email per contact." },
  { key: "tracking", name: "Follow-up tracker", description: "Sends timed follow-ups until a prospect replies." },
  { key: "meeting", name: "Meeting scheduler", description: "Books a meeting and sends a Google Meet link." },
  { key: "reply_classifier", name: "Reply reader", description: "Reads inbound replies and classifies their intent." },
];

const AGENTS: Agent[] = AGENT_META.map((m, i) => ({
  id: i + 1,
  key: m.key,
  name: m.name,
  description: m.description,
  enabled: true,
  order: i,
  status: "Idle",
  last_run: "2026-05-27T09:00:00Z",
}));

// Per-campaign pipeline: each campaign is "stopped" after a different agent so
// the demo shows the pipeline halting at various stages. `reached` is the index
// of the last agent that ran (AGENT_META order); agents past it haven't run
// (completed 0, no last_run). `totals` is the per-agent work count.
function pipelineFor(reached: number, totals: number[]): PipelineAgent[] {
  return AGENT_META.map((m, i) => {
    const total = totals[i] ?? 0;
    const done = i <= reached;
    return {
      key: m.key,
      name: m.name,
      description: m.description,
      order: i,
      status: "Idle",
      enabled: true,
      last_run: done ? "2026-06-15T09:00:00Z" : null,
      total,
      completed: done ? total : 0,
      // meeting + reply_classifier fire on their own triggers, never a button.
      runnable: m.key !== "meeting" && m.key !== "reply_classifier",
    };
  });
}

//                                  enr sco fin eml out trk mtg rep
const CAMPAIGN_PIPELINE: Record<number, PipelineAgent[]> = {
  1: pipelineFor(7, [5, 5, 4, 4, 4, 4, 4, 2]), // Running — full run, meetings + replies
  2: pipelineFor(4, [5, 5, 3, 3, 3, 3, 0, 0]), // Running — stopped after outreach
  3: pipelineFor(3, [4, 4, 2, 2, 2, 0, 0, 0]), // Paused — stopped after email verify
  4: pipelineFor(7, [5, 5, 5, 5, 5, 5, 4, 3]), // Completed — full run
  5: pipelineFor(0, [4, 4, 0, 0, 0, 0, 0, 0]), // Running — stopped after research
};

const PIPELINE = CAMPAIGN_PIPELINE[1];

const DASHBOARD: Dashboard = {
  active_campaigns: 3,
  paused_campaigns: 1,
  completed_campaigns: 1,
  companies_uploaded: 94,
  companies_researched: 94,
  emails_sent: 41,
  replies_received: 13,
  meetings_booked: 8,
  funnel: [
    { label: "Uploaded", value: 94 },
    { label: "Researched", value: 94 },
    { label: "Contacted", value: 41 },
    { label: "Replied", value: 13 },
    { label: "Meetings", value: 8 },
  ],
};

const SNAPSHOT: SnapshotStatus = { available: false, reason: "none" };

function companyDetail(id: number): CompanyDetail {
  const co = COMPANIES.find((c) => c.id === id) ?? COMPANIES[0];
  return { ...co, contacts: CONTACTS.filter((c) => c.company_id === co.id) };
}

/** Numeric id captured from a path segment, e.g. /api/campaigns/3/companies → 3. */
function idIn(path: string, pattern: RegExp): number {
  const m = path.match(pattern);
  return m ? Number(m[1]) : 0;
}

/**
 * Maps a GET request path to its static fixture. Query strings are ignored
 * (the demo never filters server-side). Unknown paths return an empty default
 * so a screen we didn't anticipate renders blank rather than crashing.
 */
export function resolveDemo<T>(rawPath: string): T {
  const path = rawPath.split("?")[0];
  let out: unknown = [];

  if (path === "/api/auth/me") out = DEMO_USER;
  else if (path === "/api/dashboard") out = DASHBOARD;
  else if (path === "/api/campaigns") out = CAMPAIGNS;
  else if (/^\/api\/campaigns\/\d+\/companies$/.test(path)) out = COMPANIES.filter((c) => c.campaign_id === idIn(path, /campaigns\/(\d+)/));
  else if (/^\/api\/campaigns\/\d+\/pipeline$/.test(path)) out = CAMPAIGN_PIPELINE[idIn(path, /campaigns\/(\d+)/)] ?? PIPELINE;
  else if (/^\/api\/campaigns\/\d+\/snapshot$/.test(path)) out = SNAPSHOT;
  else if (/^\/api\/campaigns\/\d+$/.test(path)) out = CAMPAIGNS.find((c) => c.id === idIn(path, /campaigns\/(\d+)/)) ?? CAMPAIGNS[0];
  else if (/^\/api\/companies\/\d+$/.test(path)) out = companyDetail(idIn(path, /companies\/(\d+)/));
  else if (path === "/api/contacts") out = CONTACTS;
  else if (path === "/api/emails") out = DRAFTS;
  else if (path === "/api/conversations") out = THREADS;
  else if (/^\/api\/conversations\/\d+$/.test(path)) out = THREAD_DETAILS[idIn(path, /conversations\/(\d+)/)] ?? THREAD_DETAILS[1];
  else if (path === "/api/meetings") out = MEETINGS;
  else if (path === "/api/notifications") out = NOTIFICATIONS;
  else if (path === "/api/agents") out = AGENTS;
  else if (path === "/api/logs") out = LOGS;

  return out as T;
}
