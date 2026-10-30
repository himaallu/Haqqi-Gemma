"use client";

import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Circle,
  Download,
  FileText,
  Loader2,
  Pencil,
  Phone,
  Share2,
  ShieldAlert,
  Volume2,
  Square,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { downloadComplaint } from "@/lib/api";
import { formatAed } from "@/lib/money";
import { canShareFile, pdfFile, saveFile, shareFile } from "@/lib/share";
import type { Analysis, Citation, Language } from "@/lib/types";
import { cn } from "@/lib/utils";

import { CONTRACT_XRAY } from "./data";
import {
  chipsFor,
  citationLabel,
  display,
  isoDate,
  kindOf,
  parseAmount,
  question,
  shortRef,
  type AskReply,
  type Contact,
  type Field,
  type Known,
  type LawClause,
} from "./logic";
import type { Strings } from "./strings";

export const card = "demo-in rounded-2xl border border-d-line bg-d-card p-4 shadow-sm";
export const pill =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-full px-5 text-base font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-d-primary disabled:opacity-50";
export const primaryBtn = cn(pill, "bg-d-primary text-d-on-primary hover:opacity-90");
export const ghostBtn = cn(pill, "border border-d-line bg-d-card text-d-ink hover:bg-d-primary-soft");
const chip =
  "min-h-12 rounded-full border border-d-primary/40 bg-d-primary-soft px-4 py-2 text-start text-base text-d-ink transition-colors hover:border-d-primary disabled:opacity-50";

export function citationClause(c: Citation): LawClause {
  return { chunk_id: c.chunk_id, ref_en: citationLabel(c), ref_ar: "", title: "", text_en: c.quote, text_ar: "" };
}

export function ArticleChip({ label, onOpen }: { label: string; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="inline-flex min-h-9 items-center gap-1 rounded-full bg-d-primary px-3 text-sm font-medium text-d-on-primary"
    >
      <FileText aria-hidden className="size-3.5" />
      <span dir="ltr">{label}</span>
    </button>
  );
}

const VOICE_LANG: Record<Language, string> = {
  en: "en",
  hi: "hi",
  ur: "ur",
  ar: "ar",
  ml: "ml",
  bn: "bn",
  tl: "fil",
  ne: "ne",
};

function subscribeVoices(onChange: () => void) {
  if (typeof speechSynthesis === "undefined") return () => {};
  speechSynthesis.addEventListener("voiceschanged", onChange);
  return () => speechSynthesis.removeEventListener("voiceschanged", onChange);
}

function voiceFor(lang: Language): SpeechSynthesisVoice | null {
  if (typeof speechSynthesis === "undefined") return null;
  const code = VOICE_LANG[lang];
  return speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith(code)) ?? null;
}

/** ▶ Listen, shown only when this phone has a voice for the language. Never plays on its own. */
export function ListenButton({ text, lang, s }: { text: string; lang: Language; s: Strings }) {
  const voiceName = useSyncExternalStore(subscribeVoices, () => voiceFor(lang)?.name ?? "", () => "");
  const [speaking, setSpeaking] = useState(false);
  if (!voiceName || !text) return null;
  function toggle() {
    if (speaking) {
      speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = voiceFor(lang);
    if (voice) {
      utterance.voice = voice;
      utterance.lang = voice.lang;
    }
    utterance.rate = 0.95;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    speechSynthesis.cancel();
    speechSynthesis.speak(utterance);
    setSpeaking(true);
  }
  return (
    <button type="button" onClick={toggle} className="inline-flex min-h-10 items-center gap-1.5 text-sm font-medium text-d-primary">
      {speaking ? <Square aria-hidden className="size-4" /> : <Volume2 aria-hidden className="size-4" />}
      {speaking ? s.stop : s.listen}
    </button>
  );
}

export function ShareLink({ text, s }: { text: string; s: Strings }) {
  return (
    <a
      href={`https://wa.me/?text=${encodeURIComponent(text)}`}
      target="_blank"
      rel="noreferrer"
      className="inline-flex min-h-10 items-center gap-1.5 text-sm font-medium text-d-primary"
    >
      <Share2 aria-hidden className="size-4" />
      {s.share}
    </a>
  );
}

export function ContactButtons({ contacts, tone = "plain" }: { contacts: Contact[]; tone?: "plain" | "danger" }) {
  return (
    <div className="flex flex-col gap-2">
      {contacts.map((c) => (
        <a
          key={c.number}
          href={c.number === "600590000" ? "https://wa.me/971600590000" : `tel:${c.number}`}
          className={cn(
            pill,
            "justify-between",
            tone === "danger" && ["999", "8007283"].includes(c.number)
              ? "bg-d-danger text-white"
              : "border border-d-line bg-d-card text-d-ink",
          )}
        >
          <span className="flex items-center gap-2">
            <Phone aria-hidden className="size-4" />
            {c.label}
          </span>
          <span dir="ltr" className="font-semibold">
            {c.number}
          </span>
        </a>
      ))}
    </div>
  );
}

export type FollowUp = "simpler" | "whatNow" | "check";

function sentences(text: string): string[] {
  return text.match(/[^.!?।۔؟]+[.!?।۔؟]*\s*/g)?.map((t) => t.trim()).filter(Boolean) ?? [text];
}

/** Shows the answer a sentence at a time, like someone talking, unless the reader prefers less motion. */
function useReveal(total: number, animate: boolean): number {
  const still = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const [shown, setShown] = useState(animate && !still ? 0 : total);
  useEffect(() => {
    if (shown >= total) return;
    const timer = setTimeout(() => setShown((n) => n + 1), shown === 0 ? 250 : 650);
    return () => clearTimeout(timer);
  }, [shown, total]);
  return shown;
}

export function AnswerCard(props: {
  reply: AskReply;
  lang: Language;
  s: Strings;
  active: boolean;
  animate: boolean;
  offline: boolean;
  onLaw: (c: LawClause) => void;
  onFollow: (kind: FollowUp, label: string) => void;
}) {
  const { reply, lang, s, active, animate, offline, onLaw, onFollow } = props;
  const refs = reply.citations.map((c) => shortRef(c.ref_en));
  const parts = sentences(reply.answer);
  const shown = useReveal(parts.length + 1, animate);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  const done = shown > parts.length;
  const box = useRef<HTMLDivElement>(null);
  // Once the answer has finished appearing, bring its follow-up chips into view.
  useEffect(() => {
    if (done && active && animate) box.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [done, active, animate]);
  return (
    <div ref={box} className="flex flex-col gap-2">
      <div className={cn(card, "flex flex-col gap-3")}>
        <p dir="auto" className="text-lg font-semibold leading-snug">
          {reply.headline}
        </p>
        <p dir="auto" className="leading-relaxed">
          {parts.slice(0, shown).join(" ")}
          {!done && <span className="ms-1 inline-block animate-pulse text-d-muted">●●●</span>}
        </p>
        {done && (
          <>
            <div className="flex flex-wrap gap-2">
              {reply.citations.map((c) => (
                <ArticleChip key={c.chunk_id} label={shortRef(c.ref_en)} onOpen={() => onLaw(c)} />
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-4 border-t border-d-line pt-2">
              <ListenButton text={`${reply.headline} ${reply.answer}`} lang={lang} s={s} />
              <ShareLink text={`${reply.headline}\n${reply.answer}\n(${refs.join(", ")}) — Haqqi`} s={s} />
              <span className="ms-auto flex items-center gap-1 text-sm text-d-muted">
                {feedback ? (
                  s.thanks
                ) : (
                  <>
                    <span className="me-1">{s.clear}</span>
                    <button type="button" aria-label="👍" onClick={() => setFeedback("up")} className="rounded-full p-1.5 text-lg hover:bg-d-primary-soft">
                      👍
                    </button>
                    <button type="button" aria-label="👎" onClick={() => setFeedback("down")} className="rounded-full p-1.5 text-lg hover:bg-d-primary-soft">
                      👎
                    </button>
                  </>
                )}
              </span>
            </div>
          </>
        )}
      </div>
      {done && active && reply.suggest_case && (
        <p dir="auto" className="demo-in px-1 text-sm text-d-muted">
          {s.offer}
        </p>
      )}
      {done && active && (
        <div className="demo-in flex flex-wrap gap-2">
          {!offline && (
            <>
              <FollowChip label={s.simpler} onClick={() => onFollow("simpler", s.simpler)} />
              <FollowChip label={s.whatNow} onClick={() => onFollow("whatNow", s.whatNow)} />
            </>
          )}
          {reply.suggest_case && <FollowChip label={`📋 ${s.checkCase}`} onClick={() => onFollow("check", s.checkCase)} strong />}
          <a href="tel:80084" className="min-h-11 rounded-full border border-d-line bg-d-card px-4 py-2 text-sm">
            {s.callMohre}
          </a>
        </div>
      )}
    </div>
  );
}

function FollowChip({ label, onClick, strong }: { label: string; onClick: () => void; strong?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "min-h-11 rounded-full px-4 py-2 text-start text-sm",
        strong ? "bg-d-primary text-d-on-primary" : "border border-d-primary/40 bg-d-primary-soft text-d-ink",
      )}
    >
      {label}
    </button>
  );
}

/** Reads text aloud in the worker's language, if the phone has a voice for it (the "read answers aloud" setting). */
export function speak(text: string, lang: Language): void {
  const voice = voiceFor(lang);
  if (!voice || !text) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = voice;
  utterance.lang = voice.lang;
  utterance.rate = 0.95;
  speechSynthesis.cancel();
  speechSynthesis.speak(utterance);
}

export function LawSheet({ clause, onClose, s }: { clause: LawClause; onClose: () => void; s: Strings }) {
  return (
    <div className="absolute inset-0 z-30 flex items-end bg-black/40" onClick={onClose} role="presentation">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={clause.ref_en}
        className="demo-in max-h-[80%] w-full overflow-y-auto rounded-t-3xl bg-d-card p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <p className="text-sm text-d-muted">{s.law}</p>
            <p dir="ltr" className="font-semibold">
              {clause.ref_en}
            </p>
            {clause.title && (
              <p dir="ltr" className="text-sm text-d-muted">
                {clause.title}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label={s.close} className="rounded-full p-2 hover:bg-d-primary-soft">
            <X className="size-5" />
          </button>
        </div>
        <p dir="ltr" lang="en" className="leading-relaxed">
          {clause.text_en}
        </p>
        {clause.text_ar && (
          <p dir="rtl" lang="ar" className="mt-4 border-t border-d-line pt-4 leading-loose">
            {clause.text_ar}
          </p>
        )}
      </div>
    </div>
  );
}

export function EmergencyCard({ contacts, s }: { contacts: Contact[]; s: Strings }) {
  return (
    <div className="demo-in flex flex-col gap-3 rounded-2xl border border-d-danger/40 bg-d-danger-bg p-4" role="alert">
      <p className="flex items-center gap-2 text-lg font-semibold text-d-danger">
        <ShieldAlert aria-hidden className="size-5" />
        {s.danger}
      </p>
      <ContactButtons contacts={contacts} tone="danger" />
    </div>
  );
}

const YEARS = Array.from({ length: 12 }, (_, i) => new Date().getFullYear() - i);

export function QuestionCard(props: {
  field: Field;
  step: number;
  steps: number;
  active: boolean;
  s: Strings;
  locale: string;
  onAnswer: (value: string, label: string) => void;
}) {
  const { field, step, steps, active, s, locale, onAnswer } = props;
  const [hint, setHint] = useState(false);
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [year, setYear] = useState(YEARS[0]);
  const [day, setDay] = useState("");
  const [amount, setAmount] = useState("");
  const kind = kindOf(field);
  const months = Array.from({ length: 12 }, (_, i) =>
    new Date(2024, i, 1).toLocaleDateString(locale, { month: "long" }),
  );
  return (
    <div className={cn(card, "flex flex-col gap-3", !active && "opacity-60")}>
      <div className="flex items-center gap-1.5" aria-label={`${step} / ${steps}`}>
        {Array.from({ length: steps }, (_, i) => (
          <span key={i} className={cn("h-1.5 w-6 rounded-full", i < step ? "bg-d-primary" : "bg-d-line")} />
        ))}
      </div>
      <p className="text-lg font-semibold">{question(field, s)}</p>
      {kind === "chips" && (
        <div className="flex flex-wrap gap-2">
          {chipsFor(field, s).map((c) => (
            <button key={c.value} type="button" disabled={!active} className={chip} onClick={() => onAnswer(c.value, c.label)}>
              {c.label}
            </button>
          ))}
          {field === "zone" && (
            <button type="button" disabled={!active} className={chip} onClick={() => setHint(true)}>
              {s.notSure}
            </button>
          )}
        </div>
      )}
      {hint && <p className="rounded-xl bg-d-warn-bg px-3 py-2 text-sm text-d-warn">{s.zoneHint}</p>}
      {kind === "date" && (
        <div className="flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-2">
            <select aria-label={s.month} disabled={!active} value={month} onChange={(e) => setMonth(Number(e.target.value))} className="min-h-12 rounded-xl border border-d-line bg-d-card px-3">
              {months.map((m, i) => (
                <option key={m} value={i + 1}>
                  {m}
                </option>
              ))}
            </select>
            <select aria-label={s.year} disabled={!active} value={year} onChange={(e) => setYear(Number(e.target.value))} className="min-h-12 rounded-xl border border-d-line bg-d-card px-3" dir="ltr">
              {YEARS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </div>
          <input
            inputMode="numeric"
            placeholder={s.day}
            aria-label={s.day}
            disabled={!active}
            value={day}
            onChange={(e) => setDay(e.target.value.replace(/\D/g, "").slice(0, 2))}
            className="min-h-12 rounded-xl border border-d-line bg-d-card px-3"
            dir="ltr"
          />
          <button
            type="button"
            disabled={!active}
            className={primaryBtn}
            onClick={() => {
              const d = Math.min(31, Math.max(1, Number(day) || 1));
              const value = isoDate(year, month, day ? d : null);
              onAnswer(value, display(field, value, s, locale));
            }}
          >
            {s.next}
          </button>
        </div>
      )}
      {kind === "money" && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const value = parseAmount(amount);
            if (value) onAnswer(value, `AED ${Number(value).toLocaleString("en-US")}`);
          }}
        >
          <input
            inputMode="numeric"
            aria-label={question(field, s)}
            placeholder="3000"
            disabled={!active}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="min-h-12 min-w-0 flex-1 rounded-xl border border-d-line bg-d-card px-3 text-lg"
            dir="ltr"
          />
          <button type="submit" disabled={!active || !parseAmount(amount)} className={primaryBtn}>
            {s.next}
          </button>
        </form>
      )}
    </div>
  );
}

const FACT_ROWS: [string, keyof Strings][] = [
  ["termination", "fHappened"],
  ["emirate", "fEmirate"],
  ["worker_type", "fWorker"],
  ["zone", "fZone"],
  ["start_date", "fStart"],
  ["end_date", "fEnd"],
  ["total_wage_aed", "fTotal"],
  ["basic_wage_aed", "fBasic"],
  ["notice_days_contract", "fNoticeContract"],
  ["notice_days_given", "fNoticeGiven"],
];

export function FactsCard(props: {
  known: Known;
  active: boolean;
  example: boolean;
  busy: boolean;
  s: Strings;
  locale: string;
  onEdit: (field: Field) => void;
  onConfirm: () => void;
}) {
  const { known, active, example, busy, s, locale, onEdit, onConfirm } = props;
  const editable = new Set<string>(["zone", "worker_type", "emirate", "termination", "start_date", "end_date", "total_wage_aed", "basic_wage_aed"]);
  return (
    <div className={cn(card, "flex flex-col gap-3", !active && "opacity-70")}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-lg font-semibold">{s.understood}</p>
        {example && <span className="rounded-full bg-d-warn-bg px-2 py-0.5 text-xs text-d-warn">{s.exampleTag}</span>}
      </div>
      <dl className="flex flex-col divide-y divide-d-line">
        {FACT_ROWS.filter(([f]) => known[f] && !(f === "end_date" && known.termination === "still_employed")).map(([f, label]) => (
          <div key={f} className="flex items-center justify-between gap-3 py-2">
            <dt className="text-sm text-d-muted">{s[label]}</dt>
            <dd className="flex items-center gap-2 text-end font-medium">
              <span>{display(f, known[f] ?? "", s, locale)}</span>
              {active && !example && editable.has(f) && (
                <button type="button" aria-label={`${s.edit}: ${s[label]}`} onClick={() => onEdit(f as Field)} className="rounded-full p-2 text-d-primary hover:bg-d-primary-soft">
                  <Pencil className="size-4" />
                </button>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {active && (
        <button type="button" data-tour="confirm-facts" className={primaryBtn} onClick={onConfirm} disabled={busy}>
          {busy && <Loader2 aria-hidden className="size-4 animate-spin" />}
          {s.confirm}
        </button>
      )}
    </div>
  );
}

const STAGES = ["retrieving", "calculating", "analysing", "critiquing", "writing"] as const;

export function ProgressCard({ stages, slow, s }: { stages: string[]; slow: boolean; s: Strings }) {
  const shown = STAGES.filter((st) => st !== "critiquing" || stages.includes("critiquing") || stages.includes("writing"));
  const current = stages[stages.length - 1];
  return (
    <div className={cn(card, "flex flex-col gap-2")} aria-live="polite">
      {shown.map((st) => {
        const done = stages.includes(st) && st !== current;
        const now = st === current || (st === "analysing" && current === "revising");
        return (
          <p key={st} className={cn("flex items-center gap-2", !done && !now && "text-d-muted")}>
            {done ? (
              <CheckCircle2 aria-hidden className="size-5 text-d-ok" />
            ) : now ? (
              <Loader2 aria-hidden className="size-5 animate-spin text-d-primary" />
            ) : (
              <Circle aria-hidden className="size-5" />
            )}
            {s[`st${st}` as keyof Strings]}
          </p>
        );
      })}
      {slow && <p className="mt-1 rounded-xl bg-d-warn-bg px-3 py-2 text-sm text-d-warn">{s.slowCase}</p>}
    </div>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <div className={cn(card, "flex flex-col gap-3")}>
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-lg font-semibold">{title}</p>
        {note && <span className="text-xs text-d-muted">{note}</span>}
      </div>
      {children}
    </div>
  );
}

const CONFIDENCE = { high: "strong", medium: "likely", low: "maybe" } as const;

export function ResultCards(props: {
  analysis: Analysis;
  caseId: string | null;
  stillEmployed: boolean;
  lang: Language;
  s: Strings;
  onLaw: (c: LawClause) => void;
}) {
  const { analysis, caseId, stillEmployed, lang, s, onLaw } = props;
  const writer = analysis.writer;
  const lines = [...analysis.claim];
  const plain = writer && writer.amount_lines.length >= lines.length ? writer.amount_lines : null;
  const steps = writer?.checklist.length ? writer.checklist : analysis.next_steps;
  const unpaid = analysis.violations.some((v) => v.article.article_no === 22 || v.article.article_no === 53);
  const headline = writer?.headline || s.found;
  const summary = `${headline}\n${s.total}: ${formatAed(analysis.total_aed)}\n— Haqqi`;
  return (
    <div className="flex flex-col gap-3">
      <div className={cn(card, "flex flex-col gap-3 border-d-primary/30")}>
        {analysis.replay_label && (
          <p className="self-start rounded-md border border-d-line px-2 py-1 text-xs text-d-muted" data-testid="replay-label">
            {analysis.replay_label}
          </p>
        )}
        <p dir="auto" className="text-xl font-semibold leading-snug">{headline}</p>
        {(writer?.explanation ?? analysis.explanation)
          .split(/\n+/)
          .filter(Boolean)
          .map((para, i) => (
            <p key={i} dir="auto" className="leading-relaxed">
              {para}
            </p>
          ))}
        <div className="flex flex-wrap items-center gap-4 border-t border-d-line pt-2">
          <ListenButton text={`${headline} ${writer?.explanation ?? ""}`} lang={lang} s={s} />
          <ShareLink text={summary} s={s} />
        </div>
      </div>

      {analysis.unsure && (
        <div className="demo-in flex flex-col gap-3 rounded-2xl bg-d-warn-bg p-4 text-d-warn">
          <p className="font-medium">{s.notSureCase}</p>
          <ContactButtons contacts={[{ label: "MOHRE", number: "80084" }]} />
        </div>
      )}

      {analysis.violations.length > 0 && (
        <Section title={analysis.unsure ? s.possible : s.rights} note={s.inEnglish}>
          <ul className="flex flex-col gap-3">
            {analysis.violations.map((v, i) => (
              <li key={i} className="flex flex-col gap-2 rounded-xl bg-d-bg p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <ArticleChip label={citationLabel(v.article)} onOpen={() => onLaw(citationClause(v.article))} />
                  <span className="rounded-full border border-d-line px-2 py-0.5 text-xs">{s[CONFIDENCE[v.confidence]]}</span>
                </div>
                <p dir="ltr" lang="en" className="text-start">
                  {v.issue}
                </p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {lines.length > 0 && (
        <Section title={s.owed}>
          <ul className="flex flex-col divide-y divide-d-line">
            {lines.map((line, i) => (
              <li key={i} className="flex flex-col gap-1 py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-medium">{line.item}</span>
                  <span dir="ltr" className="shrink-0 font-semibold">
                    {line.amount_aed === null ? s.notCalculated : formatAed(line.amount_aed)}
                  </span>
                </div>
                {plain?.[i] && (
                  <p dir="auto" className="text-sm">
                    {plain[i]}
                  </p>
                )}
                <p dir="ltr" className="text-start text-xs text-d-muted">
                  {line.formula}
                </p>
                {line.note && <p className="text-xs text-d-muted">{line.note}</p>}
              </li>
            ))}
          </ul>
          <div className="flex items-baseline justify-between rounded-xl bg-d-primary-soft px-3 py-3">
            <span className="font-semibold">{s.total}</span>
            <span dir="ltr" className="text-xl font-bold text-d-primary">
              {formatAed(analysis.total_aed)}
            </span>
          </div>
          <p className="flex items-center gap-1.5 text-xs text-d-muted">
            <Check aria-hidden className="size-3.5 text-d-ok" />
            {s.calcNote}
          </p>
          {analysis.above_mohre_limit && <p className="text-sm text-d-warn">{s.aboveLimit}</p>}
        </Section>
      )}

      {analysis.worker_owes.length > 0 && (
        <div className="demo-in flex flex-col gap-2 rounded-2xl bg-d-warn-bg p-4 text-d-warn">
          <p className="font-semibold">{s.youOwe}</p>
          {analysis.worker_owes.map((line, i) => (
            <p key={i} className="flex justify-between gap-3">
              <span>{line.item}</span>
              <span dir="ltr">{line.amount_aed === null ? s.notCalculated : formatAed(line.amount_aed)}</span>
            </p>
          ))}
        </div>
      )}

      <Section title={s.nextSteps}>
        <ol className="flex list-decimal flex-col gap-2 ps-5">
          {stillEmployed && unpaid && <li>{s.confidential}</li>}
          {steps.map((step, i) => (
            <li key={i} dir="auto">
              {step}
            </li>
          ))}
        </ol>
        {analysis.documents_to_gather.length > 0 && (
          <div className="flex flex-col gap-1 border-t border-d-line pt-3">
            <p className="font-medium">{s.documents}</p>
            {analysis.documents_to_gather.map((doc) => (
              <label key={doc} className="flex min-h-10 items-center gap-3">
                <input type="checkbox" className="size-5 accent-d-primary" />
                <span dir="ltr" lang="en" className="text-start">
                  {doc}
                </span>
              </label>
            ))}
          </div>
        )}
      </Section>

      {!analysis.unsure && writer?.letter_facts_ar && <ComplaintCard caseId={caseId} preview={writer.letter_facts_ar} s={s} />}
    </div>
  );
}

type PdfState = { kind: "idle" | "busy" | "error" } | { kind: "ready"; file: File; note?: string };

function ComplaintCard({ caseId, preview, s }: { caseId: string | null; preview: string; s: Strings }) {
  const [name, setName] = useState("");
  const [card_, setCard] = useState("");
  const [employer, setEmployer] = useState("");
  const [state, setState] = useState<PdfState>({ kind: "idle" });
  // A changed field means a different letter: make it again.
  const edit = (set: (v: string) => void) => (e: React.ChangeEvent<HTMLInputElement>) => {
    set(e.target.value);
    setState({ kind: "idle" });
  };
  async function create() {
    if (!caseId) return;
    setState({ kind: "busy" });
    try {
      const blob = await downloadComplaint(caseId, { name, labour_card: card_, employer });
      setState({ kind: "ready", file: pdfFile(blob, "haqqi-complaint.pdf") });
    } catch {
      setState({ kind: "error" });
    }
  }
  // Save and share are separate taps on purpose: the share sheet needs a fresh tap after the PDF is made.
  async function share(file: File) {
    if (!canShareFile(file)) {
      saveFile(file);
      setState({ kind: "ready", file, note: s.shareFallback });
      return;
    }
    try {
      await shareFile(file);
    } catch {
      saveFile(file);
      setState({ kind: "ready", file, note: s.shareFallback });
    }
  }
  const input = "min-h-12 rounded-xl border border-d-line bg-d-card px-3";
  return (
    <Section title={s.complaint}>
      <div dir="rtl" lang="ar" className="rounded-xl border border-d-line bg-d-bg p-3 text-sm leading-loose shadow-inner">
        <p className="mb-1 font-semibold">إلى وزارة الموارد البشرية والتوطين</p>
        <p className="line-clamp-4">{preview}</p>
      </div>
      {caseId && (
        <>
          <input className={input} placeholder={s.idName} aria-label={s.idName} value={name} onChange={edit(setName)} />
          <input className={input} placeholder={s.idCard} aria-label={s.idCard} value={card_} onChange={edit(setCard)} dir="ltr" />
          <input className={input} placeholder={s.idEmployer} aria-label={s.idEmployer} value={employer} onChange={edit(setEmployer)} />
          <p className="text-xs text-d-muted">{s.idNote}</p>
          {state.kind === "ready" ? (
            <div className="flex flex-col gap-2">
              <p className="flex items-center gap-2 font-medium text-d-ok">
                <CheckCircle2 aria-hidden className="size-5" />
                {s.pdfReady}
              </p>
              <button type="button" className={primaryBtn} onClick={() => saveFile(state.file)}>
                <Download aria-hidden className="size-5" />
                {s.savePdf}
              </button>
              <button type="button" className={ghostBtn} onClick={() => void share(state.file)}>
                <Share2 aria-hidden className="size-5" />
                {s.sharePdf}
              </button>
              {state.note && <p className="text-sm text-d-muted">{state.note}</p>}
            </div>
          ) : (
            <button type="button" className={primaryBtn} onClick={() => void create()} disabled={state.kind === "busy"}>
              {state.kind === "busy" ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <FileText aria-hidden className="size-4" />}
              {state.kind === "busy" ? s.preparing : s.createPdf}
            </button>
          )}
          {state.kind === "error" && <p className="text-sm text-d-danger">{s.busy}</p>}
        </>
      )}
      {!caseId && <p className="text-xs text-d-muted">{s.exampleTag}</p>}
    </Section>
  );
}

function LawChip({ clause, onLaw }: { clause: LawClause; onLaw: (c: LawClause) => void }) {
  return <ArticleChip label={shortRef(clause.ref_en)} onOpen={() => onLaw(clause)} />;
}

export function ContractCard(props: {
  lang: Language;
  stage: "intro" | "scanning" | "done";
  active: boolean;
  s: Strings;
  onStart: () => void;
  onUse: () => void;
  onLaw: (c: LawClause) => void;
}) {
  const { lang, stage, active, s, onStart, onUse, onLaw } = props;
  if (stage === "intro") {
    return (
      <div className={cn(card, "flex flex-col gap-3")}>
        <p className="leading-relaxed">{s.contractIntro}</p>
        <div className="flex flex-col gap-2">
          <button type="button" className={primaryBtn} onClick={onStart} disabled={!active}>
            {s.takePhoto}
          </button>
          <button type="button" className={ghostBtn} onClick={onStart} disabled={!active}>
            {s.pasteText}
          </button>
          <button type="button" className={ghostBtn} onClick={onStart} disabled={!active}>
            {s.sample}
          </button>
        </div>
      </div>
    );
  }
  if (stage === "scanning") {
    return (
      <div className={cn(card, "flex flex-col gap-3")}>
        <div className="relative h-40 overflow-hidden rounded-xl bg-d-bg">
          <div className="space-y-2 p-4 blur-[1.5px]">
            {Array.from({ length: 8 }, (_, i) => (
              <div key={i} className="h-2 rounded bg-d-line" style={{ width: `${60 + ((i * 17) % 40)}%` }} />
            ))}
          </div>
          <div className="demo-scan absolute inset-x-0 top-0 h-4 bg-d-primary/30 shadow-[0_0_24px_var(--d-primary)]" />
        </div>
        <p className="flex items-center gap-2 text-d-muted">
          <Loader2 aria-hidden className="size-4 animate-spin" />
          {s.scanning}
        </p>
      </div>
    );
  }
  return (
    <div className={cn(card, "flex flex-col gap-3")}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-lg font-semibold">{s.xray}</p>
        <span className="rounded-full bg-d-warn-bg px-2 py-0.5 text-xs text-d-warn">{s.sampleTag}</span>
      </div>
      <ul className="flex flex-col gap-2">
        {CONTRACT_XRAY.map((row) => (
          <li key={row.term} className={cn("flex gap-3 rounded-xl p-3", row.ok ? "bg-d-ok-bg" : "bg-d-warn-bg")}>
            {row.ok ? (
              <CheckCircle2 aria-hidden className="mt-0.5 size-5 shrink-0 text-d-ok" />
            ) : (
              <AlertTriangle aria-hidden className="mt-0.5 size-5 shrink-0 text-d-warn" />
            )}
            <div className="flex flex-col items-start gap-2">
              <p dir="auto" className="text-start">
                {lang === "ar" ? row.termAr : row.term}
              </p>
              {row.law && <LawChip clause={row.law} onLaw={onLaw} />}
            </div>
          </li>
        ))}
      </ul>
      {active && (
        <button type="button" className={primaryBtn} onClick={onUse}>
          {s.useDetails}
        </button>
      )}
    </div>
  );
}

