"use client";

import Link from "next/link";

import { ComplaintDownload } from "@/components/complaint-download";
import { MohreCall } from "@/components/mohre-call";
import { Button } from "@/components/ui/button";
import { articleRef, lawName } from "@/lib/citation";
import { useI18n } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/translate";
import { formatAed } from "@/lib/money";
import type { Analysis, Citation, ClaimLine, Confidence } from "@/lib/types";
import { groupViolations } from "@/lib/violations";

const CONFIDENCE: Record<Confidence, MessageKey> = {
  high: "results.confidence.high",
  medium: "results.confidence.medium",
  low: "results.confidence.low",
};

/**
 * Steps 4–6 (task 4.6). The Writer's text is in the worker's language; the analyst's findings,
 * formulas and law quotes are English. Every amount is the calculator's figure, shown as-is.
 * Step 7, the complaint PDF, needs the Writer's facts section and something to complain about.
 */
export function Results({ caseId, analysis, onRetry }: { caseId: string; analysis: Analysis; onRetry?: () => void }) {
  const { lang, t } = useI18n();
  const writer = analysis.writer;
  const lines = [...analysis.claim, ...analysis.worker_owes];
  // The Writer returns one plain-language line per claim line, in the same order (haqqi/agents/writer.py).
  const plain = writer && writer.amount_lines.length === lines.length ? writer.amount_lines : null;
  const nextSteps = writer?.checklist.length ? writer.checklist : analysis.next_steps;
  // Task 8.5: when no finding is more than a possibility, lead with "not sure" + MOHRE and offer no complaint.
  const unsure = analysis.unsure;
  const canComplain =
    !unsure && Boolean(writer?.letter_facts_ar) && (analysis.violations.length > 0 || analysis.claim.length > 0);

  return (
    <article className="flex flex-col gap-8" data-testid="results">
      <header className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">{t("results.title")}</p>
        {analysis.replay_label && (
          <p className="self-start rounded-md border px-2 py-1 text-xs text-muted-foreground" data-testid="replay-label">
            {analysis.replay_label}
          </p>
        )}
        {unsure && (
          <div className="flex flex-col gap-3 rounded-md bg-warning-bg px-3 py-3 text-warning-fg" data-testid="unsure">
            <p className="font-medium">{t("results.unsure")}</p>
            <MohreCall />
          </div>
        )}
        {writer && <h1 className="text-2xl font-semibold">{writer.headline}</h1>}
        {(writer?.explanation ?? analysis.explanation)
          .split(/\n+/)
          .filter(Boolean)
          .map((para, i) => (
            <p key={i} className="leading-relaxed">
              {para}
            </p>
          ))}
        {analysis.writer_failed && (
          <div className="flex flex-col gap-3 rounded-md bg-warning-bg px-3 py-3 text-warning-fg" data-testid="writer-failed">
            <p>{t("results.writerFailed")}</p>
            {onRetry && (
              <Button variant="outline" onClick={onRetry}>
                {t("common.retry")}
              </Button>
            )}
          </div>
        )}
      </header>

      <Section title={t(unsure ? "results.possibleIssues" : "results.violations")} note={t("results.inEnglish")}>
        {analysis.violations.length === 0 ? (
          <p>{t("results.noViolations")}</p>
        ) : (
          <ul className="flex flex-col gap-3" data-testid="violations">
            {groupViolations(analysis.violations).map((finding, i) => (
              <li key={i} className="flex flex-col gap-2 rounded-lg border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  {finding.citations.map((citation) => (
                    <ArticleChip key={citation.chunk_id} citation={citation} />
                  ))}
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{t(CONFIDENCE[finding.confidence])}</span>
                </div>
                <p lang="en" dir="ltr" className="text-start">
                  {finding.issue}
                </p>
                {finding.citations.map((citation) => (
                  <LawQuote
                    key={citation.chunk_id}
                    citation={citation}
                    label={finding.citations.length > 1 ? articleRef(citation) : undefined}
                  />
                ))}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {analysis.claim.length > 0 && (
        <Section title={t(unsure ? "results.claimIfApplies" : "results.claim")}>
          <ClaimList lines={analysis.claim} plain={plain} />
          <div className="flex items-baseline justify-between gap-4 border-t pt-3 text-lg font-semibold" data-testid="total">
            <span>{t("results.total")}</span>
            <span dir="ltr">{formatAed(analysis.total_aed)}</span>
          </div>
          {analysis.above_mohre_limit && (
            <p className="rounded-md bg-warning-bg px-3 py-2 text-sm text-warning-fg">{t("results.aboveLimit")}</p>
          )}
        </Section>
      )}

      {analysis.worker_owes.length > 0 && (
        <Section title={t("results.workerOwes")} note={t("results.workerOwesHelp")}>
          <ClaimList lines={analysis.worker_owes} plain={plain?.slice(analysis.claim.length) ?? null} />
        </Section>
      )}

      {nextSteps.length > 0 && (
        <Section title={t("results.nextSteps")}>
          <ol className="list-decimal space-y-2 ps-6">
            {nextSteps.map((step, i) => (
              <li key={i} lang={writer?.checklist.length ? lang : "en"}>
                {step}
              </li>
            ))}
          </ol>
        </Section>
      )}

      <EnglishList title={t("results.documents")} items={analysis.documents_to_gather} />
      <EnglishList title={t("results.notCovered")} items={analysis.not_covered} />
      {analysis.time_limit_note && (
        <Section title={t("results.timeLimit")}>
          <p lang="en" dir="ltr" className="text-start">
            {analysis.time_limit_note}
          </p>
        </Section>
      )}

      {canComplain && <ComplaintDownload caseId={caseId} />}

      <div className="flex flex-col gap-3">
        <p className="text-xs text-muted-foreground">{t("results.gemini")}</p>
        <Button asChild variant="outline">
          <Link href={`/${lang}`}>{t("common.startOver")}</Link>
        </Button>
      </div>
    </article>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-xl font-semibold">{title}</h2>
      {note && <p className="text-sm text-muted-foreground">{note}</p>}
      {children}
    </section>
  );
}

function ArticleChip({ citation }: { citation: Citation }) {
  const { t } = useI18n();
  return (
    <span className="rounded-full border px-2.5 py-0.5 text-sm font-medium" data-testid="article">
      {t("results.article", { article: articleRef(citation) })}
      <span className="text-muted-foreground"> · </span>
      <span lang="en" className="text-muted-foreground">
        {lawName(citation)}
      </span>
    </span>
  );
}

/** Native <details>: expandable without JavaScript and announced correctly by screen readers. */
function LawQuote({ citation, label }: { citation: Citation; label?: string }) {
  const { t } = useI18n();
  const suffix = label ? ` (${label})` : "";
  return (
    <details className="group text-sm">
      <summary className="flex min-h-11 cursor-pointer items-center text-muted-foreground underline-offset-4 hover:underline">
        <span className="group-open:hidden">{t("results.showLaw")}{suffix}</span>
        <span className="hidden group-open:inline">{t("results.hideLaw")}{suffix}</span>
      </summary>
      <blockquote lang="en" dir="ltr" className="border-s-2 ps-3 text-start whitespace-pre-line">
        {citation.quote}
      </blockquote>
    </details>
  );
}

function ClaimList({ lines, plain }: { lines: ClaimLine[]; plain: string[] | null }) {
  const { t } = useI18n();
  return (
    <ul className="flex flex-col gap-3" data-testid="claim">
      {lines.map((line, i) => (
        <li key={i} className="flex flex-col gap-2 rounded-lg border p-4">
          <div className="flex items-baseline justify-between gap-4">
            <span lang="en" className="font-medium">
              {line.item}
            </span>
            <span dir="ltr" className="shrink-0 font-semibold" data-testid="amount">
              {line.amount_aed === null ? t("results.notCalculated") : formatAed(line.amount_aed)}
            </span>
          </div>
          {plain?.[i] && <p>{plain[i]}</p>}
          <p className="text-sm text-muted-foreground">
            {t("results.formula")}:{" "}
            <span lang="en" dir="ltr" className="inline-block" data-testid="formula">
              {line.formula}
            </span>
          </p>
          {line.note && (
            <p lang="en" dir="ltr" className="text-sm text-start">
              {line.note}
            </p>
          )}
          <ArticleChip citation={line.article} />
        </li>
      ))}
    </ul>
  );
}

function EnglishList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <Section title={title}>
      <ul lang="en" dir="ltr" className="list-disc space-y-1 ps-6 text-start">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </Section>
  );
}
