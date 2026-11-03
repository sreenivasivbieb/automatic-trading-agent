import { useEffect, useState } from "react";
import { FileCheck2, ExternalLink } from "lucide-react";
import { api } from "./api";
import type { Run } from "./types";
import {
  Badge,
  Modal,
  Panel,
  StatusBadge,
  money,
  number,
  timestamp,
} from "./ui";

type Finding = {
  domain: string;
  status: string;
  summary: string;
  metrics: Record<string, unknown>;
};
export type ResearchReport = {
  schema_version: number;
  run_id: string;
  symbol: string;
  mode: string;
  run_status: string;
  recorded_at: string;
  decision: string;
  headline: string;
  rationale: string;
  execution_status: string;
  agreement: Record<string, number>;
  findings: Finding[];
  citations: {
    id: string;
    title: string;
    publisher: string;
    url: string | null;
    published_at: string | null;
    retrieved_at: string | null;
    fixture: boolean;
    stale: boolean;
    relevant: boolean;
  }[];
  gaps: string[];
  risk_flags: string[];
  risk_plan: {
    verdict: string;
    requested_notional: string | null;
    approved_notional: string | null;
    reference_price: string | null;
    stop_price: string | null;
    estimated_loss_at_stop: string | null;
    expected_costs: string | null;
    exit_policy: string | null;
    checks: {
      code: string;
      passed: boolean;
      actual: unknown;
      limit: unknown;
      reason: string;
    }[];
    reasons: string[];
    note: string;
  };
  execution: Record<string, unknown>;
  methodology: string;
  receipt: {
    algorithm: string;
    digest: string;
    canonical_payload: string;
    scope: string;
  };
};

function ordered(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(ordered);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b, "en"))
        .map(([key, child]) => [key, ordered(child)]),
    );
  return value;
}

export async function verifyReport(report: ResearchReport): Promise<boolean> {
  const { receipt, ...body } = report;
  if (
    receipt.algorithm !== "SHA-256" ||
    JSON.stringify(ordered(body)) !==
      JSON.stringify(ordered(JSON.parse(receipt.canonical_payload)))
  )
    return false;
  const hash = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(receipt.canonical_payload),
  );
  const digest = Array.from(new Uint8Array(hash), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
  return digest === receipt.digest;
}

function MetricValues({ metrics }: { metrics: Record<string, unknown> }) {
  return (
    <dl className="brief-values">
      {Object.entries(metrics)
        .filter(([, value]) => value != null)
        .map(([key, value]) => (
          <div key={key}>
            <dt>{key.replaceAll("_", " ")}</dt>
            <dd>
              {typeof value === "number"
                ? number(value, 4)
                : typeof value === "object"
                  ? JSON.stringify(value)
                  : String(value)}
            </dd>
          </div>
        ))}
    </dl>
  );
}

export function ResearchBrief({ run }: { run: Run }) {
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState("Checking snapshot");
  const [open, setOpen] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let alive = true;
    setReport((previous) => (previous?.run_id === run.id ? previous : null));
    setError("");
    setReceipt("Checking snapshot");
    void api<ResearchReport>(`/runs/${encodeURIComponent(run.id)}/brief`)
      .then(async (result) => {
        let verified = false;
        try {
          verified = await verifyReport(result);
        } catch {
          /* Unavailable WebCrypto never earns a verified badge. */
        }
        if (alive) {
          setReport(result);
          setReceipt(
            verified
              ? "Snapshot integrity verified"
              : "Snapshot integrity unverified",
          );
        }
      })
      .catch((e) => {
        if (alive)
          setError(
            e instanceof Error ? e.message : "Research brief is unavailable",
          );
      });
    return () => {
      alive = false;
    };
  }, [run.id, run.ended_at, run.intent?.state, retry]);
  const risk = report?.risk_plan;
  return (
    <>
      <Panel
        title="Research brief & evidence"
        subtitle="A readable report from this recorded cycle, with its original sources and risk gates"
        className="section-gap"
        action={
          report && (
            <button className="button secondary" onClick={() => setOpen(true)}>
              <FileCheck2 size={15} />
              Read evidence report
            </button>
          )
        }
      >
        <div className="research-brief-body">
          {error ? (
            <div role="alert" className="brief-error">
              <p>{error}</p>
              <button
                className="button secondary"
                onClick={() => setRetry((v) => v + 1)}
              >
                Retry research brief
              </button>
            </div>
          ) : !report ? (
            <p className="muted" role="status">
              Compiling recorded evidence…
            </p>
          ) : (
            <>
              <div className="inline gap wrap">
                <StatusBadge value={report.decision} />
                <Badge>{report.execution_status.replaceAll("_", " ")}</Badge>
                <Badge>{report.mode}</Badge>
                <Badge>
                  {receipt === "Snapshot integrity verified"
                    ? "Local snapshot verified"
                    : "Local snapshot unverified"}
                </Badge>
              </div>
              <p className="brief-rationale">{report.rationale}</p>
              <div className="brief-summary">
                <div>
                  <span>Recorded rule signals</span>
                  <strong>
                    {report.agreement.BUY} buy · {report.agreement.SELL} sell ·{" "}
                    {report.agreement.HOLD} hold
                  </strong>
                </div>
                <div>
                  <span>Risk verdict</span>
                  <strong>{risk?.verdict.replaceAll("_", " ")}</strong>
                </div>
                <div>
                  <span>Approved notional</span>
                  <strong>
                    {risk?.approved_notional == null
                      ? "Not evaluated"
                      : money(risk.approved_notional)}
                  </strong>
                </div>
                <div>
                  <span>Evidence sources</span>
                  <strong>
                    {report.citations.length} captured · {report.gaps.length}{" "}
                    gaps
                  </strong>
                </div>
              </div>
            </>
          )}
        </div>
      </Panel>
      {open && report && risk && (
        <Modal
          title={`${report.symbol} research evidence`}
          close={() => setOpen(false)}
          wide
        >
          <div className="research-report">
            <div className="inline gap wrap">
              <StatusBadge value={report.decision} />
              <Badge>{report.mode}</Badge>
              <span>{timestamp(report.recorded_at)}</span>
            </div>
            <h3>{report.headline}</h3>
            <p>{report.rationale}</p>
            <div className="brief-domains">
              {report.findings.map((f) => (
                <section key={f.domain}>
                  <div className="inline gap wrap">
                    <h3>{f.domain}</h3>
                    <StatusBadge value={f.status} />
                  </div>
                  <p>{f.summary}</p>
                  <MetricValues metrics={f.metrics} />
                </section>
              ))}
            </div>
            <section>
              <h3>Risk & position plan</h3>
              <MetricValues
                metrics={{
                  requested_notional: risk.requested_notional,
                  approved_notional: risk.approved_notional,
                  reference_price: risk.reference_price,
                  stop_price: risk.stop_price,
                  estimated_loss_at_stop_before_costs:
                    risk.estimated_loss_at_stop,
                  expected_costs: risk.expected_costs,
                }}
              />
              <p>{risk.exit_policy ?? "No position proposed."}</p>
              {risk.reasons.map((reason, i) => (
                <p key={i}>{reason}</p>
              ))}
              <p className="note">{risk.note}</p>
              {!!risk.checks.length && (
                <details>
                  <summary>
                    {risk.checks.length} recorded risk checks ·{" "}
                    {risk.checks.filter((c) => !c.passed).length} blocked at
                    capture
                  </summary>
                  <div className="brief-checks">
                    {risk.checks.map((check, i) => (
                      <div key={`${check.code}-${i}`}>
                        <StatusBadge
                          value={check.passed ? "PASS" : "BLOCKED"}
                        />
                        <strong>{check.code.replaceAll("_", " ")}</strong>
                        <p>{check.reason}</p>
                        <small>
                          Observed {String(check.actual)} · limit{" "}
                          {String(check.limit)}
                        </small>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </section>
            <section>
              <h3>Execution receipt</h3>
              <MetricValues
                metrics={{
                  state: report.execution_status,
                  ...report.execution,
                }}
              />
            </section>
            <section>
              <h3>Source evidence</h3>
              <p className="note">
                Captured publisher context. These links do not verify a model's
                claims.
              </p>
              {!report.citations.length ? (
                <p>No publisher metadata captured for this cycle.</p>
              ) : (
                <ol className="brief-citations">
                  {report.citations.map((c) => (
                    <li key={c.id}>
                      <div className="inline gap wrap">
                        <strong>{c.publisher}</strong>
                        {c.fixture && <Badge>FIXTURE</Badge>}
                        {c.stale && <Badge>STALE AT CAPTURE</Badge>}
                        {c.relevant && <Badge>{report.symbol} tagged</Badge>}
                      </div>
                      <p>
                        {c.url && /^https?:\/\//i.test(c.url) ? (
                          <a href={c.url} target="_blank" rel="noreferrer">
                            {c.title} <ExternalLink size={13} />
                          </a>
                        ) : (
                          c.title
                        )}
                      </p>
                      <small>
                        Published {timestamp(c.published_at)} · captured{" "}
                        {timestamp(c.retrieved_at)}
                      </small>
                    </li>
                  ))}
                </ol>
              )}
            </section>
            <section>
              <h3>Evidence gaps & risk flags</h3>
              <ul>
                {[...report.gaps, ...report.risk_flags].map((g, i) => (
                  <li key={i}>{g}</li>
                ))}
              </ul>
            </section>
            <section
              className="brief-integrity"
              aria-label="Research report integrity"
            >
              <strong>{receipt}</strong>
              <code>{report.receipt.digest}</code>
              <p>{report.receipt.scope}</p>
              <p className="note">{report.methodology}</p>
            </section>
          </div>
        </Modal>
      )}
    </>
  );
}
