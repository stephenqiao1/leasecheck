"use client";

import { useState } from "react";
import {
  type ReviewView,
  type Verdict,
  type FindingStatus,
  updateFindingStatus,
} from "@/lib/api";
import styles from "./document.module.css";

const RAIL: Record<Verdict, string> = {
  violation: styles.railViolation,
  unclear: styles.railUnclear,
  ok: styles.railOk,
};

const DOT: Record<Verdict, string> = {
  violation: styles.dot_violation,
  unclear: styles.dot_unclear,
  ok: styles.dot_ok,
};

const STATUS_CLASS: Record<FindingStatus, string> = {
  pending: styles.statusPending,
  accepted: styles.statusAccepted,
  dismissed: styles.statusDismissed,
};

export default function ReviewDocument({ data }: { data: ReviewView }) {
  const hasFindings = data.clauses.some((c) => c.finding !== null);

  // Local overrides of finding status, keyed by finding id. Absent = use the
  // server-provided value.
  const [statuses, setStatuses] = useState<Record<string, FindingStatus>>({});
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [errored, setErrored] = useState<Record<string, boolean>>({});

  const statusOf = (id: string, fallback: FindingStatus): FindingStatus =>
    statuses[id] ?? fallback;

  // Live triage counts: a violation still counts as "pending" until it is
  // accepted or dismissed. Recomputed from current state on every render.
  const totalViolations = data.clauses.filter(
    (c) => c.finding?.verdict === "violation",
  ).length;
  const pendingViolations = data.clauses.filter(
    (c) =>
      c.finding?.verdict === "violation" &&
      statusOf(c.finding.id, c.finding.status) === "pending",
  ).length;

  async function changeStatus(
    findingId: string,
    fallback: FindingStatus,
    next: FindingStatus,
  ) {
    const previous = statusOf(findingId, fallback);
    setPending((p) => ({ ...p, [findingId]: true }));
    setErrored((e) => ({ ...e, [findingId]: false }));
    setStatuses((s) => ({ ...s, [findingId]: next })); // optimistic
    try {
      const updated = await updateFindingStatus(findingId, next);
      setStatuses((s) => ({ ...s, [findingId]: updated.status }));
    } catch {
      setStatuses((s) => ({ ...s, [findingId]: previous })); // roll back
      setErrored((e) => ({ ...e, [findingId]: true }));
    } finally {
      setPending((p) => ({ ...p, [findingId]: false }));
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <h1 className={styles.docTitle}>{data.filename}</h1>
          <div className={styles.meta}>
            <span>
              Jurisdiction<span className={styles.metaVal}>{data.jurisdiction}</span>
            </span>
            <span>
              Clauses<span className={styles.metaVal}>{data.clause_count}</span>
            </span>
            <span aria-label={`${pendingViolations} pending violations of ${totalViolations} total`}>
              Violations pending
              <span
                className={`${styles.metaVal} ${
                  pendingViolations > 0 ? styles.metaViolation : ""
                }`}
              >
                {pendingViolations} / {totalViolations}
              </span>
            </span>
          </div>
        </div>
      </header>

      {!hasFindings && (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>Not yet reviewed</p>
          <p>
            This document has been parsed into {data.clause_count} clauses, but no
            compliance findings have been generated yet. Run a review to annotate
            the text.
          </p>
        </div>
      )}

      <div className={styles.doc}>
        {data.clauses.map((clause) => {
          const finding = clause.finding;
          const status = finding ? statusOf(finding.id, finding.status) : null;
          const railClass = finding
            ? `${RAIL[finding.verdict]} ${
                status === "dismissed" ? styles.railMuted : ""
              }`
            : "";

          return (
            <article key={clause.id} className={styles.clauseRow}>
              <p className={`${styles.clauseText} ${railClass}`}>
                <span className={styles.ordinal}>{clause.ordinal}</span>
                {clause.text}
              </p>

              {finding && status && (
                <aside
                  className={`${styles.annotation} ${
                    status === "dismissed" ? styles.annotationDismissed : ""
                  }`}
                >
                  <span className={styles.verdictTag}>
                    <span className={`${styles.dot} ${DOT[finding.verdict]}`} />
                    {finding.verdict}
                  </span>
                  {finding.rule_code && (
                    <div className={styles.ruleCode}>{finding.rule_code}</div>
                  )}
                  {finding.rule_title && (
                    <div className={styles.ruleTitle}>{finding.rule_title}</div>
                  )}
                  <p className={styles.rationale}>{finding.rationale}</p>

                  <div className={styles.actions}>
                    <span className={`${styles.statusLabel} ${STATUS_CLASS[status]}`}>
                      {status}
                    </span>
                    {status !== "accepted" && (
                      <button
                        type="button"
                        className={styles.actionBtn}
                        disabled={pending[finding.id]}
                        aria-label={`Accept finding on clause ${clause.ordinal}`}
                        onClick={() =>
                          changeStatus(finding.id, finding.status, "accepted")
                        }
                      >
                        Accept
                      </button>
                    )}
                    {status !== "dismissed" && (
                      <button
                        type="button"
                        className={styles.actionBtn}
                        disabled={pending[finding.id]}
                        aria-label={`Dismiss finding on clause ${clause.ordinal}`}
                        onClick={() =>
                          changeStatus(finding.id, finding.status, "dismissed")
                        }
                      >
                        Dismiss
                      </button>
                    )}
                    {errored[finding.id] && (
                      <span className={styles.actionError} role="alert">
                        couldn&apos;t save
                      </span>
                    )}
                  </div>
                </aside>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
