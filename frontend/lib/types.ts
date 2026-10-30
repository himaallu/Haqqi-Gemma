/** Mirrors backend/haqqi/models.py and haqqi/api/cases.py. Money is a decimal string (AED), never a number. */

export type Language = "en" | "hi" | "ur" | "ml" | "bn" | "tl" | "ne" | "ar";
export type Emirate =
  | "abu_dhabi"
  | "dubai"
  | "sharjah"
  | "ajman"
  | "umm_al_quwain"
  | "ras_al_khaimah"
  | "fujairah";
export type Zone = "mainland" | "free_zone" | "difc" | "adgm";
export type WorkerType = "private_sector" | "domestic";
export type ContractType = "full_time" | "part_time" | "temporary" | "flexible";
export type Termination = "employer" | "resigned" | "still_employed";
export type Confidence = "high" | "medium" | "low";
export type Referral = "domestic" | "difc_adgm" | "free_zone";
export type CaseStatus = "out_of_scope" | "need_info" | "ready" | "confirmed" | "analysed";
export type Money = string;

export const EMIRATES: Emirate[] = [
  "abu_dhabi",
  "dubai",
  "sharjah",
  "ajman",
  "umm_al_quwain",
  "ras_al_khaimah",
  "fujairah",
];
export const ZONES: Zone[] = ["mainland", "free_zone", "difc", "adgm"];
export const WORKER_TYPES: WorkerType[] = ["private_sector", "domestic"];
export const CONTRACT_TYPES: ContractType[] = ["full_time", "part_time", "temporary", "flexible"];
export const TERMINATIONS: Termination[] = ["employer", "resigned", "still_employed"];

export type ExtractedFacts = {
  language: Language | null;
  issue_types: string[];
  emirate: Emirate | null;
  zone: Zone | null;
  free_zone_name: string | null;
  worker_type: WorkerType | null;
  contract_type: ContractType | null;
  weekly_hours: string | null;
  start_date: string | null;
  end_date: string | null;
  basic_wage_aed: Money | null;
  total_wage_aed: Money | null;
  months_unpaid: number | null;
  deducted_amount_aed: Money | null;
  deducted_monthly_aed: Money | null;
  unused_leave_days: number | null;
  unpaid_absence_days: number | null;
  termination: Termination | null;
  notice_days_contract: number | null;
  notice_days_given: number | null;
  in_scope: boolean | null;
  scope_reason: string;
  missing_info: string[];
  facts_summary_en: string;
};

export type Citation = {
  chunk_id: string;
  law_id: string;
  article_no: number;
  clause_no: number | null;
  quote: string;
};

export type Violation = { issue: string; article: Citation; confidence: Confidence };

export type ClaimLine = {
  item: string;
  amount_aed: Money | null;
  formula: string;
  article: Citation;
  note: string;
};

export type WriterOutput = {
  headline: string;
  explanation: string;
  amount_lines: string[];
  checklist: string[];
  letter_facts_ar: string;
  letter_facts_translation: string;
};

export type Analysis = {
  in_scope: boolean;
  referral: string | null;
  violations: Violation[];
  not_covered: string[];
  claim: ClaimLine[];
  worker_owes: ClaimLine[];
  total_aed: Money;
  above_mohre_limit: boolean;
  explanation: string;
  next_steps: string[];
  documents_to_gather: string[];
  time_limit_note: string;
  critic_verdict: "pass" | "revise" | null;
  revised: boolean;
  writer: WriterOutput | null;
  writer_failed: boolean;
  replay_label?: string | null; // DEMO_REPLAY: replies replayed from a recorded Gemma 4 run
  unsure: boolean; // no finding above "low" confidence (task 8.5)
};

export type CaseView = {
  id: string;
  status: CaseStatus;
  extracted: ExtractedFacts;
  missing: string[];
  missing_fields: string[];
  referral: string | null;
  referral_kind: Referral | null;
  confirmed: Record<string, unknown> | null;
  analysis: Analysis | null;
};
