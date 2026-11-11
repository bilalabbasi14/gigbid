import type { Page, Route } from "@playwright/test";

// Stateful stand-in for the FastAPI backend. Shapes follow src/lib/api/schema.d.ts.
export type MockOptions = { onboarded?: boolean; marketplaceDown?: boolean; signedIn?: boolean };

export const THREAD = "bid-test0001";
const EV1 = "aaaa1111bbbb2222";
const EV2 = "cccc3333dddd4444";
const LETTER =
  `You need a chatbot that answers questions from your PDF manuals with citations, in two weeks.\n\n` +
  `I built a RAG system over contracts with LangChain and pgvector that reached 94% citation accuracy [${EV1}]. ` +
  `It ran as a FastAPI service with nightly ingestion [${EV2}].\n\n` +
  `I would start with a one-day ingestion spike on three PDFs, then build retrieval and answers with evaluation on twenty real questions.`;

function proposalPayload(letter = LETTER, revision = 0) {
  return {
    kind: "proposal",
    job_id: "job_test_1",
    thread_id: THREAD,
    draft: {
      job_id: "job_test_1",
      cover_letter: letter,
      screening_answers: [`I built a contract RAG bot with 94% citation accuracy [${EV1}].`],
      evidence_ids: [EV1, EV2],
      revision,
      word_count: letter.split(/\s+/).length,
      claims: [{ claim_id: "c1", text: "I built a RAG system over contracts with LangChain and pgvector that reached 94% citation accuracy", cited_evidence_ids: [EV1], label: "supported", support_score: 0.81, best_evidence_id: EV1, action: "keep" }],
      verification: { claims: 1, unsupported_rate_before: 0, unsupported_rate_after: 0, removed: 0, rewritten: 0 },
    },
    evidence: [
      { evidence_id: EV1, title: "Legal contract RAG bot", type: "case_study", project_id: "p07", excerpt: "Built a RAG system over contracts with LangChain and pgvector, citation accuracy 94%.", source: "data/personas/ai_ml/case_studies/cs_07.md", year: 2023, outcome: null, score: 0.82 },
      { evidence_id: EV2, title: "legal-contract-bot", type: "readme", project_id: "p07", excerpt: "FastAPI service, pgvector index, nightly ingestion.", source: "data/personas/ai_ml/repos/legal-contract-bot/README.md", year: 2023, outcome: null, score: 0.7 },
    ],
    risk: { score: 0.1, flags: [], scam_likely: false, injection_detected: false, injection_patterns: [], client_quality: 0.8, explanation: "Verified client with spend." },
    price: { bid_type: "fixed", amount: 1100, floor: 100, connects_cost: 8, connects_balance: 92, expected_value: 300, worth_connects: true, rationale: "client budget $1200, bidding 92% given fit 0.85", policy_version: 1 },
    fit: { score: 0.85, matrix: [], matched_skills: ["LangChain"], missing_skills: [], evidence_ids: [EV1, EV2], reasons: [] },
    job_spec: { job_id: "job_test_1", title: "Build a RAG chatbot over PDFs", summary: "RAG chatbot over PDF manuals.", deliverables: ["chatbot"], required_skills: ["Python"], nice_to_have_skills: [], budget_type: "fixed", screening_questions: ["Describe a similar project."], hidden_needs: [], red_flags_in_text: [] },
    critique: { passed: true, grounding_score: 0.9, personalisation_score: 0.85, length_ok: true, issues: [], revision_instructions: "", round: 0 },
    compliance: { allowed: true, violations: [], policy_version: 1, reason: "no violations" },
    dry_run_preview: { connects_cost: 8, balance_after: 92, bid_amount: 1100 },
    connects_cost: 8,
  };
}

export class MockApi {
  state: { user: Record<string, unknown> | null; settings: Record<string, unknown>; approval: ReturnType<typeof proposalPayload> | null; decisions: Record<string, unknown>[]; marketplaceDown: boolean };
  constructor(opts: MockOptions = {}) {
    this.state = {
      user: opts.signedIn === false ? null : { user_id: "usr_1", email: "reviewer@gigbid.local", display_name: "Reviewer", role: "reviewer", persona: "ai_ml", onboarded: opts.onboarded ?? true, settings: { onboarded: opts.onboarded ?? true, persona: "ai_ml" } },
      settings: {},
      approval: proposalPayload(),
      decisions: [],
      marketplaceDown: !!opts.marketplaceDown,
    };
  }

  async install(page: Page) {
    await page.route("**/api/**", (route) => this.handle(route));
  }

  private json(route: Route, body: unknown, status = 200) {
    return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  }

  private async handle(route: Route) {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = req.method();
    const body = req.postData() ? (() => { try { return JSON.parse(req.postData()!); } catch { return {}; } })() : {};
    const s = this.state;

    if (path === "/health") return this.json(route, { status: s.marketplaceDown ? "degraded" : "ok", marketplace_mode: "gigsim", marketplace_reachable: !s.marketplaceDown, degraded: s.marketplaceDown ? { marketplace: { since: 0, error: "503" } } : {}, policy_version: 1, model_profile: "open" });
    if (path === "/auth/me") return s.user ? this.json(route, s.user) : this.json(route, { detail: "not signed in" }, 401);
    if (path === "/auth/login" || path === "/auth/register") {
      s.user = s.user ?? { user_id: "usr_1", email: body.email, display_name: body.display_name || "New", role: "user", persona: "ai_ml", onboarded: path === "/auth/login", settings: {} };
      return this.json(route, s.user, path === "/auth/register" ? 201 : 200);
    }
    if (path === "/auth/logout") return route.fulfill({ status: 204 });
    if (path === "/settings" && method === "PUT") {
      s.settings = { ...s.settings, ...body };
      s.user = { ...s.user!, persona: body.persona ?? s.user!.persona, onboarded: body.onboarded ?? s.user!.onboarded, settings: { ...(s.user!.settings as object), ...body } };
      return this.json(route, s.user);
    }
    if (path === "/settings/searches") return method === "POST" ? this.json(route, { search_id: "srch_1", ...body }, 201) : this.json(route, []);
    if (path === "/settings/accounts") return this.json(route, [{ provider: "gigsim", connected: true, scopes: "simulator" }, { provider: "upwork", connected: false, scopes: "" }, { provider: "github", connected: false, scopes: "" }]);
    if (path === "/settings/memory") return this.json(route, { style: [], outcome: [], candidates: [] });
    if (path === "/portfolio") return this.json(route, { persona: "ai_ml", persona_key: "ai_ml", editable: false, counts: { case_studies: 15, repos: 8, proposals: 60, reviews: 12, cv: 1 }, projects: [{ id: "p07", name: "Legal contract RAG bot", year: 2023, skills: [], has_repo: true }], top_skills: ["Python", "LangChain"], items: [], indexed_chunks: 225 });
    if (path === "/jobs" && method === "GET")
      return this.json(route, { total: 1, items: [{ job_id: "job_test_1", title: "Build a RAG chatbot over PDFs", status: s.approval ? "drafted" : "submitted", decision: "bid", fit_score: 0.85, risk_score: 0.1, risk_flags: [], price_amount: 1100, price_type: "fixed", connects_cost: 8, payment_type: "fixed", budget: 1200, first_seen_at: new Date().toISOString(), latest_thread_id: THREAD, recommended_action: "review proposal" }] });
    if (path === "/approvals") return this.json(route, { items: s.approval ? [{ thread_id: THREAD, kind: "proposal", job_id: "job_test_1", title: "Build a RAG chatbot over PDFs", created_at: new Date().toISOString(), proposal: s.approval }] : [] });
    if (path === `/approvals/${THREAD}` && method === "GET") {
      if (!s.approval) return this.json(route, { detail: "run is not awaiting approval (status submitted)" }, 409);
      return this.json(route, { thread_id: THREAD, kind: "proposal", job_id: "job_test_1", title: "Build a RAG chatbot over PDFs", created_at: new Date().toISOString(), proposal: s.approval });
    }
    if (path === `/approvals/${THREAD}` && method === "POST") {
      s.decisions.push(body);
      if (body.action === "approve") {
        s.approval = null;
        return this.json(route, { thread_id: THREAD, status: "submitted", submission: { proposal_id: "prop_1", status: "viewed", connects_spent: 8 }, promoted_style_rules: [] });
      }
      if (body.action === "reject") {
        s.approval = null;
        return this.json(route, { thread_id: THREAD, status: "rejected", promoted_style_rules: [] });
      }
      s.approval = proposalPayload(body.edited_cover_letter, 1);
      return this.json(route, { thread_id: THREAD, status: "awaiting_approval", promoted_style_rules: [], next_proposal: s.approval });
    }
    if (path === "/pipeline" || path === "/pipeline/sync") return this.json(route, { columns: { drafted: [], submitted: [], viewed: [], replied: [], interview: [], hired: [], lost: [] } });
    if (path === "/messages/threads") return this.json(route, []);
    if (path === "/runs") return this.json(route, []);
    return this.json(route, { detail: `no mock for ${method} ${path}` }, 404);
  }
}
