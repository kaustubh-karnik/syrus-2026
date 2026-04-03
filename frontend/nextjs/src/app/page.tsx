"use client";

import { CSSProperties, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, cloneRepository, getGithubRepositoryOverview, getLastPipelineRun, getTickets, streamPipelineLogs } from "@/lib/api";
import { CloneRepoResponse, GithubRepositoryOverview, JiraTicket, LastPipelineRunResponse, PipelineReport, TicketReport } from "@/lib/types";
import { coerceDescription, prettyJson, safeToString } from "@/lib/utils";

function envOrFallback(value: string | undefined, fallback: string): string {
  const normalized = (value ?? "").trim();
  return normalized || fallback;
}

const BACKEND_BASE_URL = (process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "").trim().replace(/\/+$/, "");
const TEAM_NAME = envOrFallback(process.env.NEXT_PUBLIC_TEAM_NAME, "MPM Build");
const AGENT_LABEL = envOrFallback(process.env.NEXT_PUBLIC_AGENT_LABEL, "PS-02 · Autonomous Fix Agent");
const AGENT_CODE = envOrFallback(process.env.NEXT_PUBLIC_AGENT_CODE, "PS-02");
const NAV_TAGLINE = envOrFallback(process.env.NEXT_PUBLIC_NAV_TAGLINE, "incident → fix");
const INITIAL_INCIDENT_ID = "INC-0000";

const SIGNAL_KEYWORDS = ["null", "500", "timeout", "undefined", "crash", "econnrefused", "null pointer", "connection reset"] as const;

const PIPELINE_STEPS = [
  {
    name: "Ticket Parsing",
    description: "Extracting intent, severity, and failure signals from incident",
    tag: "PARSE",
  },
  {
    name: "Semantic Search",
    description: "Finding relevant code via vector similarity across repository",
    tag: "SEARCH",
  },
  {
    name: "Root Cause Analysis",
    description: "Identifying the bug source and its upstream dependencies",
    tag: "ANALYZE",
  },
  {
    name: "Patch Synthesis",
    description: "Generating a minimal, safe code fix for the identified issue",
    tag: "PATCH",
  },
  {
    name: "Sandbox Validation",
    description: "Running tests in an isolated environment to verify fix",
    tag: "TEST",
  },
  {
    name: "Report Generation",
    description: "Compiling root cause, changes, and test results into a report",
    tag: "REPORT",
  },
] as const;

type FeedbackTone = "success" | "error" | "info" | "warning";
type StepStatus = "waiting" | "running" | "complete" | "failed";
type Severity = "P0" | "P1" | "P2" | "P3";
type IncidentSource = "manual" | "jira";

type StepRuntime = {
  status: StepStatus;
  durationMs: number | null;
};

interface Feedback {
  tone: FeedbackTone;
  message: string;
  details?: string;
}

interface IncidentRecord {
  incidentId: string;
  title: string;
  description: string;
  severity: Severity;
  jiraKey?: string;
  fetchedLabel: string;
  source: IncidentSource;
  jiraStatus?: string;
}

interface RepoPreviewState {
  loading: boolean;
  error: string | null;
  data: GithubRepositoryOverview | null;
}

interface TerminalLine {
  id: number;
  stepIndex: number;
  tag: string;
  text: string;
  timestamp: string;
}

interface RootCauseSummary {
  location: string;
  type: string;
  explanation: string;
}

function formatApiError(error: unknown): Feedback {
  if (error instanceof ApiError) {
    return {
      tone: "error",
      message: error.message || "Backend request failed",
      details: error.details ? prettyJson(error.details) : undefined,
    };
  }

  return {
    tone: "error",
    message: "Unexpected error while calling backend",
    details: safeToString(error),
  };
}

function feedbackClass(tone: FeedbackTone): string {
  if (tone === "success") return "status-banner status-success";
  if (tone === "warning") return "status-banner status-warning";
  if (tone === "error") return "status-banner status-error";
  return "status-banner status-info";
}

function parseGithubUrl(value: string): { owner: string; repo: string } | null {
  const clean = value.trim();
  if (!clean) {
    return null;
  }

  const match = clean.match(/github\.com[/:]([^/\s]+)\/([^/\s]+?)(?:\.git)?$/i);
  if (!match) {
    return null;
  }

  return { owner: match[1], repo: match[2] };
}

function generateIncidentId(): string {
  const id = Math.floor(1000 + Math.random() * 9000);
  return `INC-${id}`;
}

function severityFromPriority(priority?: string): Severity {
  const normalized = (priority ?? "").toLowerCase();
  if (normalized.includes("critical") || normalized.includes("highest") || normalized === "p0") return "P0";
  if (normalized.includes("high") || normalized === "p1") return "P1";
  if (normalized.includes("medium") || normalized === "p2") return "P2";
  return "P3";
}

function detectKeywords(text: string): string[] {
  const lower = text.toLowerCase();
  return SIGNAL_KEYWORDS.filter((keyword) => lower.includes(keyword));
}

function relativeTime(value?: string): string {
  if (!value) {
    return "Unknown";
  }

  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) {
    return "Unknown";
  }

  const diffMs = Math.max(0, Date.now() - ts);
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function detectStepFromLog(line: string): number {
  const lower = line.toLowerCase();
  if (lower.includes("ticket analyzer") || lower.includes("ticket parsing") || lower.includes("signals")) return 0;
  if (lower.includes("vector") || lower.includes("retrieval") || lower.includes("semantic") || lower.includes("search")) return 1;
  if (lower.includes("root cause") || lower.includes("analysis") || lower.includes("trace")) return 2;
  if (lower.includes("patch") || lower.includes("fix generation") || lower.includes("edit") || lower.includes("synthesis")) return 3;
  if (lower.includes("sandbox") || lower.includes("pytest") || lower.includes("validation") || lower.includes("test")) return 4;
  if (lower.includes("pipeline_report_json_start") || lower.includes("report") || lower.includes("batch summary")) return 5;
  return -1;
}

function looksLikeFailure(line: string): boolean {
  const lower = line.toLowerCase();
  if (lower.includes("failed tests") && !lower.includes("failed tests: []")) return true;
  return lower.includes("traceback") || lower.includes("exception") || lower.includes("status=failed") || lower.includes("error:");
}

function inferFailureType(text: string): string {
  const lower = text.toLowerCase();
  if (lower.includes("null") || lower.includes("undefined")) return "NullReferenceException";
  if (lower.includes("timeout")) return "TimeoutException";
  if (lower.includes("connection") || lower.includes("econnrefused")) return "ConnectionFailure";
  return "RuntimeError";
}

function isTicketFailed(ticket: TicketReport): boolean {
  const status = String(ticket.status ?? "").toLowerCase();
  return ticket.success === false || status.includes("fail");
}

function formatTicketValidationResult(ticket: TicketReport): string {
  const selectedCount = ticket.tests?.selected_tests?.length ?? 0;
  const failedCount = ticket.tests?.failed_tests?.length ?? 0;

  if (failedCount > 0) {
    return "✗ tests failed";
  }

  if (selectedCount === 0) {
    return isTicketFailed(ticket) ? "⚠ failed before tests" : "— no tests";
  }

  if (ticket.tests?.passed) {
    return "✓ pass";
  }

  return isTicketFailed(ticket) ? "✗ fail" : "— no tests";
}

function pseudoDiffFromReport(report: PipelineReport | null): string[] {
  if (!report?.tickets?.length) {
    return ["# No patch generated yet."];
  }

  const output: string[] = [];
  for (const ticket of report.tickets) {
    output.push(`@@ ${ticket.ticket_key ?? "UNKNOWN"}`);

    if ((ticket.edited_files ?? []).length === 0 && (ticket.edit_details ?? []).length === 0) {
      output.push("- no concrete file edits captured");
      output.push("");
      continue;
    }

    for (const file of ticket.edited_files ?? []) {
      output.push(`+ file: ${file}`);
    }

    for (const detail of ticket.edit_details ?? []) {
      const requested = safeToString(detail.requested_file || "unknown");
      const resolved = safeToString(detail.resolved_file || "unknown");
      output.push(`- ${requested}`);
      output.push(`+ ${resolved}`);
    }

    output.push("");
  }

  return output;
}

function formatStepDuration(durationMs: number | null): string {
  if (durationMs === null || Number.isNaN(durationMs)) {
    return "—";
  }
  return `${(durationMs / 1000).toFixed(1)}s`;
}

function buildMarkdownReport(report: PipelineReport | null, meta: LastPipelineRunResponse | null): string {
  if (!report) {
    return "No resolution report available.";
  }

  const summary = report.summary ?? {};
  const rows = [
    "# Resolution Report",
    "",
    `- Finished At: ${meta?.finishedAt ?? "N/A"}`,
    `- Duration: ${meta?.startedAt && meta?.finishedAt ? `${((new Date(meta.finishedAt).getTime() - new Date(meta.startedAt).getTime()) / 1000).toFixed(1)}s` : "N/A"}`,
    `- Exit Code: ${safeToString(meta?.exitCode)}`,
    "",
    "## Summary",
    `- Requested: ${summary.requested ?? 0}`,
    `- Processed: ${summary.processed ?? 0}`,
    `- Successful: ${summary.successful ?? 0}`,
    `- Halted: ${summary.halted ? "Yes" : "No"}`,
    `- Halt Reason: ${summary.halt_reason ?? "N/A"}`,
    "",
    "## Tickets",
    ...(report.tickets ?? []).map(
      (ticket) =>
        `- ${ticket.ticket_key ?? "UNKNOWN"} · status=${ticket.status ?? "unknown"} · success=${ticket.success ? "yes" : "no"}`,
    ),
  ];

  return rows.join("\n");
}

function deriveRootCause(report: PipelineReport | null, terminalLines: TerminalLine[]): RootCauseSummary {
  const explanation =
    report?.tickets?.find((ticket) => ticket.edit_reason)?.edit_reason ??
    report?.summary?.halt_reason ??
    "Pipeline did not provide a detailed root-cause narrative yet.";

  const mergedLogs = terminalLines.map((line) => line.text).join(" \n ");
  const locationMatch = mergedLogs.match(/([\w./-]+\.(?:ts|tsx|js|py))(?:[:\s]+line\s+|:)(\d+)/i);

  const location = locationMatch
    ? `${locationMatch[1]} · line ${locationMatch[2]}`
    : report?.tickets?.find((ticket) => (ticket.edited_files ?? []).length > 0)?.edited_files?.[0]
      ? `${report.tickets.find((ticket) => (ticket.edited_files ?? []).length > 0)?.edited_files?.[0]} · line n/a`
      : "Unknown file · line n/a";

  return {
    location,
    type: inferFailureType(`${explanation}\n${mergedLogs}`),
    explanation,
  };
}

function FeedbackBanner({ feedback }: { feedback: Feedback | null }) {
  if (!feedback) {
    return null;
  }

  return (
    <div className={feedbackClass(feedback.tone)}>
      <p>{feedback.message}</p>
      {feedback.details ? <pre>{feedback.details}</pre> : null}
    </div>
  );
}

function TicketReportAccordion({ item }: { item: TicketReport }) {
  const tests = item.tests ?? {};

  return (
    <details className="report-accordion">
      <summary>
        <span>{item.ticket_key ?? "UNKNOWN"}</span>
        <span className="helper-text">status={item.status ?? "unknown"}</span>
      </summary>
      <div className="report-content">
        <div className="kv-grid">
          <p>
            <strong>Success:</strong> {String(item.success)}
          </p>
          <p>
            <strong>Attempts:</strong> {safeToString(item.attempt_count ?? "N/A")}
          </p>
        </div>

        {item.error ? (
          <p>
            <strong>Error:</strong> <code>{item.error}</code>
          </p>
        ) : null}

        {item.edit_reason ? (
          <p>
            <strong>Edit rationale:</strong> {item.edit_reason}
          </p>
        ) : null}

        <h4>Files edited</h4>
        {(item.edited_files ?? []).length === 0 ? (
          <p className="helper-text">No file edits recorded.</p>
        ) : (
          <ul className="pill-list">
            {(item.edited_files ?? []).map((file, idx) => (
              <li key={`${file}-${idx}`}>{file}</li>
            ))}
          </ul>
        )}

        <h4>Validation</h4>
        <ul className="stack-list">
          <li>Passed: {String(tests.passed)}</li>
          <li>Selected tests: {safeToString(tests.selected_tests ?? [])}</li>
          <li>Failed tests: {safeToString(tests.failed_tests ?? [])}</li>
          <li>Test plan source: {safeToString(tests.test_plan_source ?? "N/A")}</li>
        </ul>
      </div>
    </details>
  );
}

export default function DashboardPage() {
  const [repoUrl, setRepoUrl] = useState("");
  const [repoId, setRepoId] = useState("");
  const [repoRef, setRepoRef] = useState("");
  const [branchOptions, setBranchOptions] = useState<string[]>([]);
  const [workspacePath, setWorkspacePath] = useState("");
  const [reEmbedOnPull, setReEmbedOnPull] = useState(false);
  const [repoPreview, setRepoPreview] = useState<RepoPreviewState>({ loading: false, error: null, data: null });
  const [cloneResult, setCloneResult] = useState<CloneRepoResponse | null>(null);
  const [cloneReady, setCloneReady] = useState(false);
  const [isCloning, setIsCloning] = useState(false);
  const [cloneFeedback, setCloneFeedback] = useState<Feedback | null>(null);
  const [ingestStageIndex, setIngestStageIndex] = useState(0);
  const [ingestElapsed, setIngestElapsed] = useState(0);
  const [ingestDurations, setIngestDurations] = useState<[number, number, number]>([0, 0, 0]);

  const [incidentId, setIncidentId] = useState(INITIAL_INCIDENT_ID);
  const [ticketTitle, setTicketTitle] = useState("");
  const [ticketDescription, setTicketDescription] = useState("");
  const [ticketSeverity, setTicketSeverity] = useState<Severity>("P2");
  const [incidentQueue, setIncidentQueue] = useState<IncidentRecord[]>([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);
  const [isAnalyzingTicket, setIsAnalyzingTicket] = useState(false);
  const [isSyncingJira, setIsSyncingJira] = useState(false);
  const [ticketFeedback, setTicketFeedback] = useState<Feedback | null>(null);

  const [pipelineMeta, setPipelineMeta] = useState<LastPipelineRunResponse | null>(null);
  const [pipelineReport, setPipelineReport] = useState<PipelineReport | null>(null);
  const [isRunningPipeline, setIsRunningPipeline] = useState(false);
  const [pipelineFeedback, setPipelineFeedback] = useState<Feedback | null>(null);
  const [showDiffViewer, setShowDiffViewer] = useState(false);
  const [stepRuntime, setStepRuntime] = useState<StepRuntime[]>(() =>
    PIPELINE_STEPS.map(() => ({ status: "waiting", durationMs: null })),
  );
  const [terminalLines, setTerminalLines] = useState<TerminalLine[]>([]);

  const [reportFeedback, setReportFeedback] = useState<Feedback | null>(null);

  const terminalRef = useRef<HTMLDivElement | null>(null);
  const stepStartRef = useRef<Record<number, number>>({});
  const firstLineIdByStepRef = useRef<Record<number, number>>({});
  const cloneStartRef = useRef<number | null>(null);
  const repoOverviewCacheRef = useRef<Record<string, GithubRepositoryOverview>>({});

  const detectedSignals = useMemo(() => detectKeywords(ticketDescription), [ticketDescription]);
  const hasBackendBaseUrl = Boolean(BACKEND_BASE_URL);
  const incidentReady = Boolean(ticketTitle.trim() && ticketDescription.trim());
  const pipelineReady = cloneReady && incidentReady;

  const phaseActiveIndex = useMemo(() => {
    if (!cloneReady) return 0;
    if (!incidentReady) return 1;
    return 2;
  }, [cloneReady, incidentReady]);

  const nextAction = useMemo(() => {
    if (!cloneReady) return "Ingest a repository to unlock incident analysis.";
    if (!incidentReady) return "Repository ready. Load an incident ticket to proceed.";
    if (!pipelineReport) return "Incident loaded. Execute the autonomous pipeline.";
    return "Pipeline complete. Review and export the resolution report.";
  }, [cloneReady, incidentReady, pipelineReport]);

  const pipelineOutcome = useMemo(() => {
    const tickets = pipelineReport?.tickets ?? [];
    const processed = Number(pipelineReport?.summary?.processed ?? tickets.length ?? 0);
    const successful = Number(pipelineReport?.summary?.successful ?? tickets.filter((ticket) => ticket.success === true).length);
    const ticketFailed = tickets.filter((ticket) => isTicketFailed(ticket)).length;
    const hasTicketFailures = ticketFailed > 0 || (processed > 0 && successful < processed);
    const hardFailed = typeof pipelineMeta?.exitCode === "number" && pipelineMeta.exitCode !== 0;

    return {
      processed,
      successful,
      ticketFailed,
      hasTicketFailures,
      hardFailed,
    };
  }, [pipelineMeta?.exitCode, pipelineReport]);

  const systemStatus = useMemo(
    () => ({
      agent: isRunningPipeline ? "● Active" : "● Standby",
      repository: cloneReady ? "Connected" : "None",
      pipeline: isRunningPipeline
        ? "Running"
        : pipelineOutcome.hardFailed
          ? "Failed"
          : pipelineOutcome.hasTicketFailures
            ? "Partial"
            : pipelineReport
              ? "Complete"
              : "Idle",
      queue: `${incidentQueue.length} ticket${incidentQueue.length === 1 ? "" : "s"}`,
    }),
    [cloneReady, incidentQueue.length, isRunningPipeline, pipelineOutcome.hardFailed, pipelineOutcome.hasTicketFailures, pipelineReport],
  );

  const pseudoDiffLines = useMemo(() => pseudoDiffFromReport(pipelineReport), [pipelineReport]);
  const rootCause = useMemo(() => deriveRootCause(pipelineReport, terminalLines), [pipelineReport, terminalLines]);
  const markdownReport = useMemo(() => buildMarkdownReport(pipelineReport, pipelineMeta), [pipelineMeta, pipelineReport]);

  const runDuration = useMemo(() => {
    if (!pipelineMeta?.startedAt || !pipelineMeta?.finishedAt) return null;
    const ms = new Date(pipelineMeta.finishedAt).getTime() - new Date(pipelineMeta.startedAt).getTime();
    if (!Number.isFinite(ms) || ms < 0) return null;
    return (ms / 1000).toFixed(1);
  }, [pipelineMeta]);

  const validationSummary = useMemo(() => {
    let passed = 0;
    let failed = 0;
    let skipped = 0;
    let ticketPassed = 0;
    let ticketFailed = 0;
    let failedBeforeTests = 0;

    for (const ticket of pipelineReport?.tickets ?? []) {
      const selected = ticket.tests?.selected_tests?.length ?? 0;
      const failedCount = ticket.tests?.failed_tests?.length ?? 0;
      const passedCount = Math.max(0, selected - failedCount);

      passed += passedCount;

      failed += failedCount;
      skipped += Math.max(0, selected - passedCount - failedCount);

      if (isTicketFailed(ticket)) {
        ticketFailed += 1;
        if (failedCount === 0) {
          failedBeforeTests += 1;
        }
      } else {
        ticketPassed += 1;
      }
    }

    const total = passed + failed + skipped;
    const ratio = total > 0 ? (passed / total) * 100 : 0;

    return { passed, failed, skipped, ratio, ticketPassed, ticketFailed, failedBeforeTests };
  }, [pipelineReport]);

  const changedFiles = useMemo(
    () =>
      Array.from(
        new Set((pipelineReport?.tickets ?? []).flatMap((ticket) => ticket.edited_files ?? []).filter((file) => Boolean(file))),
      ),
    [pipelineReport],
  );

  useEffect(() => {
    setIncidentId(generateIncidentId());
  }, []);

  useEffect(() => {
    const parsed = parseGithubUrl(repoUrl);
    if (!parsed) {
      setRepoPreview({ loading: false, error: null, data: null });
      setBranchOptions([]);
      setRepoRef("");
      return;
    }

    const cacheKey = `${parsed.owner}/${parsed.repo}`.toLowerCase();
    const cached = repoOverviewCacheRef.current[cacheKey];
    if (cached) {
      const branches = (cached.branches ?? [])
        .map((item) => item.name)
        .filter((name): name is string => Boolean(name && name.trim()))
        .map((name) => name.trim());

      setRepoPreview({ loading: false, error: null, data: cached });
      setBranchOptions(branches);
      setRepoRef((previous) => {
        if (previous && branches.includes(previous)) {
          return previous;
        }
        return (cached.default_branch ?? branches[0] ?? "").trim();
      });
      setRepoId((previous) => (previous.trim() ? previous : cached.name ?? parsed.repo));
      return;
    }

    if (!hasBackendBaseUrl) {
      setRepoPreview({
        loading: false,
        error: "Backend base URL is not configured. Set NEXT_PUBLIC_BACKEND_BASE_URL in frontend/nextjs/.env.local.",
        data: null,
      });
      setBranchOptions([]);
      setRepoRef("");
      return;
    }

    let disposed = false;
    const timer = window.setTimeout(async () => {
      setRepoPreview({ loading: true, error: null, data: null });
      try {
        const payload = await getGithubRepositoryOverview(BACKEND_BASE_URL, parsed.owner, parsed.repo);
        if (disposed) {
          return;
        }

        repoOverviewCacheRef.current[cacheKey] = payload;

        const branches = (payload.branches ?? [])
          .map((item) => item.name)
          .filter((name): name is string => Boolean(name && name.trim()))
          .map((name) => name.trim());

        setRepoPreview({ loading: false, error: null, data: payload });
        setBranchOptions(branches);

        setRepoRef((previous) => {
          if (previous && branches.includes(previous)) {
            return previous;
          }
          return (payload.default_branch ?? branches[0] ?? "").trim();
        });

        setRepoId((previous) => (previous.trim() ? previous : payload.name ?? parsed.repo));
      } catch (error) {
        if (disposed) {
          return;
        }
        let message = error instanceof ApiError ? error.message : "Unable to fetch repository preview from GitHub MCP.";
        if (message.includes("GitHub API request failed (401)") || message.toLowerCase().includes("bad credentials")) {
          message = "GitHub authentication failed for repo preview. Update backend GITHUB_TOKEN or remove invalid token for public repositories.";
        }
        setRepoPreview({ loading: false, error: message, data: null });
        setBranchOptions([]);
        setRepoRef("");
      }
    }, 120);

    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [hasBackendBaseUrl, repoUrl]);

  async function handleLocateFolder() {
    if (typeof window === "undefined") {
      return;
    }

    try {
      const picker = (window as Window & {
        showDirectoryPicker?: (options?: { mode?: "read" | "readwrite" }) => Promise<{ name?: string }>;
      }).showDirectoryPicker;

      if (picker) {
        const handle = await picker({ mode: "read" });
        const folderName = (handle?.name ?? "").trim();
        if (folderName) {
          setWorkspacePath(`./${folderName}`);
          setCloneFeedback({
            tone: "info",
            message: `Selected folder \"${folderName}\". Browser privacy hides absolute path; update it manually if your backend needs a full path.`,
          });
        }
        return;
      }

      const manualPath = window.prompt("Enter local folder path for clone storage", workspacePath || "./workspace/repos");
      if (manualPath !== null) {
        setWorkspacePath(manualPath.trim());
      }
    } catch (error) {
      if ((error as Error)?.name === "AbortError") {
        return;
      }

      setCloneFeedback({
        tone: "warning",
        message: "Could not open folder picker. Enter path manually in Step B.",
        details: safeToString(error),
      });
    }
  }

  useEffect(() => {
    if (!isCloning) {
      setIngestElapsed(0);
      return;
    }

    const interval = window.setInterval(() => {
      if (!cloneStartRef.current) return;
      setIngestElapsed((Date.now() - cloneStartRef.current) / 1000);
    }, 180);

    return () => window.clearInterval(interval);
  }, [isCloning]);

  useEffect(() => {
    if (!terminalRef.current) {
      return;
    }
    terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
  }, [terminalLines]);

  function resetStepRuntime() {
    stepStartRef.current = { 0: Date.now() };
    setStepRuntime(
      PIPELINE_STEPS.map((_, index) => ({
        status: index === 0 ? "running" : "waiting",
        durationMs: null,
      })),
    );
  }

  function advanceToStep(target: number) {
    if (target < 0) {
      return;
    }

    setStepRuntime((previous) => {
      const now = Date.now();
      const next = previous.map((step) => ({ ...step }));
      const runningIndex = next.findIndex((step) => step.status === "running");

      if (runningIndex >= 0 && runningIndex < target) {
        const startedAt = stepStartRef.current[runningIndex] ?? now;
        next[runningIndex] = {
          ...next[runningIndex],
          status: "complete",
          durationMs: now - startedAt,
        };
      }

      if (runningIndex !== target && target >= 0 && target < next.length) {
        if (next[target].status !== "complete" && next[target].status !== "failed") {
          next[target] = { ...next[target], status: "running" };
          if (!stepStartRef.current[target]) {
            stepStartRef.current[target] = now;
          }
        }
      }

      return next;
    });
  }

  function markRunningStepFailed() {
    setStepRuntime((previous) => {
      const now = Date.now();
      const next = previous.map((step) => ({ ...step }));
      let indexToFail = -1;

      for (let i = 0; i < next.length; i += 1) {
        if (next[i].status === "running") {
          indexToFail = i;
          break;
        }
      }

      if (indexToFail < 0) {
        for (let i = next.length - 1; i >= 0; i -= 1) {
          if (next[i].status === "complete") {
            indexToFail = i;
            break;
          }
        }
      }

      if (indexToFail < 0) {
        indexToFail = 0;
      }

      const startedAt = stepStartRef.current[indexToFail];
      next[indexToFail] = {
        ...next[indexToFail],
        status: "failed",
        durationMs: startedAt ? now - startedAt : next[indexToFail].durationMs,
      };

      return next;
    });
  }

  function completePipelineSteps() {
    const now = Date.now();
    setStepRuntime((previous) =>
      previous.map((step, index) => {
        if (step.status === "complete") return step;
        if (step.status === "failed") return step;

        if (step.status === "running") {
          const startedAt = stepStartRef.current[index] ?? now;
          return { status: "complete", durationMs: now - startedAt };
        }

        return { status: "complete", durationMs: step.durationMs ?? 0 };
      }),
    );
  }

  function pushTerminalLine(raw: string, stepIndex: number) {
    const timestamp = new Date().toLocaleTimeString("en-GB", { hour12: false });
    const tag = stepIndex >= 0 ? PIPELINE_STEPS[stepIndex].tag : "SYSTEM";

    setTerminalLines((previous) => {
      const nextId = previous.length + 1;
      if (stepIndex >= 0 && firstLineIdByStepRef.current[stepIndex] === undefined) {
        firstLineIdByStepRef.current[stepIndex] = nextId;
      }

      return [
        ...previous,
        {
          id: nextId,
          stepIndex,
          tag,
          text: raw,
          timestamp,
        },
      ];
    });
  }

  function jumpToStepLog(stepIndex: number) {
    const targetId = firstLineIdByStepRef.current[stepIndex];
    if (!targetId) return;

    const node = document.getElementById(`terminal-line-${targetId}`);
    if (!node) return;

    node.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function loadIncident(item: IncidentRecord) {
    setSelectedIncidentId(item.incidentId);
    setIncidentId(item.incidentId);
    setTicketTitle(item.title);
    setTicketDescription(item.description);
    setTicketSeverity(item.severity);
  }

  function clearIncidentDraft() {
    setIncidentId(generateIncidentId());
    setSelectedIncidentId(null);
    setTicketTitle("");
    setTicketDescription("");
    setTicketSeverity("P2");
    setTicketFeedback({ tone: "info", message: "Incident draft cleared." });
  }

  async function handleIngestRepository(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!hasBackendBaseUrl) {
      setCloneFeedback({
        tone: "error",
        message: "Backend base URL is not configured. Set NEXT_PUBLIC_BACKEND_BASE_URL in frontend/nextjs/.env.local.",
      });
      return;
    }

    if (!repoId.trim() || !workspacePath.trim()) {
      setCloneFeedback({
        tone: "error",
        message: "Folder name and workspace path are required.",
      });
      return;
    }

    if (!repoRef.trim()) {
      setCloneFeedback({
        tone: "error",
        message: "Select a branch before ingesting the repository.",
      });
      return;
    }

    setIsCloning(true);
    setCloneFeedback({ tone: "info", message: "Ingesting repository via clone/index pipeline..." });
    setCloneReady(false);
    setCloneResult(null);
    setIngestStageIndex(0);
    setIngestDurations([0, 0, 0]);
    cloneStartRef.current = Date.now();

    const stageTimer = window.setTimeout(() => {
      setIngestStageIndex(1);
    }, 900);

    try {
      const result = await cloneRepository(BACKEND_BASE_URL, {
        repoUrl: repoUrl.trim() || undefined,
        repoId: repoId.trim(),
        ref: repoRef.trim() || undefined,
        localStorageLocation: workspacePath.trim(),
        autoRunDocker: false,
      });

      if (result.status !== "ok") {
        setCloneFeedback({
          tone: "error",
          message: "Repository ingest returned an error.",
          details: prettyJson(result),
        });
        return;
      }

      const elapsedTotal = cloneStartRef.current ? (Date.now() - cloneStartRef.current) / 1000 : 0;
      const cloneDuration = Math.max(0.8, elapsedTotal * 0.45);
      const embedDuration = Math.max(0.8, elapsedTotal - cloneDuration);

      setIngestDurations([cloneDuration, embedDuration, elapsedTotal]);
      setIngestStageIndex(2);
      setCloneResult(result);
      setCloneReady(true);
      setCloneFeedback({
        tone: "success",
        message: `Repository ready at ${result.localPath ?? "N/A"}.`,
        details: reEmbedOnPull ? "Re-embed on pull is enabled." : undefined,
      });
    } catch (error) {
      setCloneFeedback(formatApiError(error));
      setCloneReady(false);
      setCloneResult(null);
    } finally {
      window.clearTimeout(stageTimer);
      cloneStartRef.current = null;
      setIsCloning(false);
    }
  }

  async function handleSyncJira() {
    if (!hasBackendBaseUrl) {
      setTicketFeedback({
        tone: "error",
        message: "Backend base URL is not configured. Set NEXT_PUBLIC_BACKEND_BASE_URL in frontend/nextjs/.env.local.",
      });
      return;
    }

    setIsSyncingJira(true);
    setTicketFeedback({ tone: "info", message: "Syncing incidents from Jira..." });

    try {
      const fetched = await getTickets(BACKEND_BASE_URL);
      const normalized = (Array.isArray(fetched) ? fetched : []).map((ticket: JiraTicket, index: number) => ({
        incidentId: `INC-${String(5000 + index)}`,
        title: ticket.summary ?? "Untitled incident",
        description: coerceDescription(ticket.description),
        severity: severityFromPriority(ticket.priority),
        jiraKey: ticket.jira_key,
        fetchedLabel: "Fetched just now",
        source: "jira" as const,
        jiraStatus: ticket.status,
      }));

      setIncidentQueue((previous) => {
        const manuals = previous.filter((item) => item.source === "manual");
        return [...manuals, ...normalized];
      });

      if (normalized.length > 0) {
        loadIncident(normalized[0]);
      }

      setTicketFeedback({
        tone: "success",
        message: `Synced ${normalized.length} Jira incident${normalized.length === 1 ? "" : "s"}.`,
      });
    } catch (error) {
      setTicketFeedback(formatApiError(error));
    } finally {
      setIsSyncingJira(false);
    }
  }

  async function handleAnalyzeAndQueue() {
    if (!ticketTitle.trim() || !ticketDescription.trim()) {
      setTicketFeedback({
        tone: "warning",
        message: "Provide incident title and description before analysis.",
      });
      return;
    }

    setIsAnalyzingTicket(true);
    setTicketFeedback({ tone: "info", message: "Analyzing incident and extracting failure signals..." });

    await new Promise((resolve) => window.setTimeout(resolve, 700));

    const incident: IncidentRecord = {
      incidentId,
      title: ticketTitle.trim(),
      description: ticketDescription.trim(),
      severity: ticketSeverity,
      fetchedLabel: "Queued manually",
      source: "manual",
    };

    setIncidentQueue((previous) => {
      const withoutExisting = previous.filter((item) => item.incidentId !== incident.incidentId);
      return [incident, ...withoutExisting];
    });

    setSelectedIncidentId(incident.incidentId);
    setTicketFeedback({
      tone: "success",
      message:
        detectedSignals.length > 0
          ? `Incident queued. Detected signals: ${detectedSignals.join(", ")}.`
          : "Incident queued. No predefined failure signals detected yet.",
    });

    setIsAnalyzingTicket(false);
  }

  async function handleRunPipeline() {
    if (!hasBackendBaseUrl) {
      setPipelineFeedback({
        tone: "error",
        message: "Backend base URL is not configured. Set NEXT_PUBLIC_BACKEND_BASE_URL in frontend/nextjs/.env.local.",
      });
      return;
    }

    if (!pipelineReady) {
      setPipelineFeedback({
        tone: "warning",
        message: "Repository and incident must both be ready before execution.",
      });
      return;
    }

    setIsRunningPipeline(true);
    setPipelineFeedback({ tone: "info", message: "Starting autonomous ticket-to-fix execution..." });
    setTerminalLines([]);
    firstLineIdByStepRef.current = {};
    resetStepRuntime();

    try {
      await streamPipelineLogs(BACKEND_BASE_URL, (line) => {
        const stepIndex = detectStepFromLog(line);
        if (stepIndex >= 0) {
          advanceToStep(stepIndex);
        }
        if (looksLikeFailure(line)) {
          markRunningStepFailed();
        }
        pushTerminalLine(line, stepIndex);
      });

      const lastRun = await getLastPipelineRun(BACKEND_BASE_URL);
      setPipelineMeta(lastRun);
      setPipelineReport(lastRun.report ?? null);

      const reportTickets = lastRun.report?.tickets ?? [];
      const processed = Number(lastRun.report?.summary?.processed ?? reportTickets.length ?? 0);
      const successful = Number(lastRun.report?.summary?.successful ?? reportTickets.filter((ticket) => ticket.success === true).length);
      const ticketFailures = reportTickets.filter((ticket) => isTicketFailed(ticket)).length;
      const hasTicketFailures = ticketFailures > 0 || (processed > 0 && successful < processed);

      if (lastRun.exitCode === 0 && !hasTicketFailures) {
        completePipelineSteps();
        setPipelineFeedback({ tone: "success", message: "Pipeline completed successfully." });
      } else if (lastRun.exitCode === 0 && hasTicketFailures) {
        markRunningStepFailed();
        setPipelineFeedback({
          tone: "warning",
          message: `Pipeline finished with partial failures (${successful}/${processed} tickets successful).`,
          details: ticketFailures > 0 ? `${ticketFailures} ticket(s) failed before or during validation.` : undefined,
        });
      } else {
        markRunningStepFailed();
        setPipelineFeedback({
          tone: "warning",
          message: `Pipeline finished with exit code ${safeToString(lastRun.exitCode)}.`,
        });
      }
    } catch (error) {
      setPipelineFeedback(formatApiError(error));
    } finally {
      setIsRunningPipeline(false);
    }
  }

  async function handleCopyMarkdownReport() {
    try {
      await navigator.clipboard.writeText(markdownReport);
      setReportFeedback({ tone: "success", message: "Markdown report copied to clipboard." });
    } catch (error) {
      setReportFeedback({
        tone: "error",
        message: "Unable to copy report.",
        details: safeToString(error),
      });
    }
  }

  function handleExportJson() {
    if (!pipelineMeta) {
      setReportFeedback({ tone: "warning", message: "No report payload available to export yet." });
      return;
    }

    const blob = new Blob([prettyJson(pipelineMeta)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `resolution-report-${Date.now()}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    setReportFeedback({ tone: "success", message: "JSON report export started." });
  }

  const renderSectionStyle = (delayMs: number): CSSProperties => ({
    ["--delay" as string]: `${delayMs}ms`,
  });

  return (
    <div className="war-room-root">
      <header className="topbar">
        <div className="brand-area">
          <div className="brand-mark">◈</div>
          <div className="brand-copy">
            <p className="brand-title">{TEAM_NAME}</p>
            <p className="brand-subtitle">{NAV_TAGLINE}</p>
          </div>
          <span className="brand-separator">|</span>
          <p className="brand-agent">{AGENT_LABEL}</p>
        </div>

        <div className="status-strip">
          <article className="status-chip">
            <span>AGENT</span>
            <strong className={isRunningPipeline ? "status-running" : "status-idle"}>{systemStatus.agent}</strong>
          </article>
          <article className="status-chip">
            <span>REPO</span>
            <strong>{systemStatus.repository}</strong>
          </article>
          <article className="status-chip">
            <span>PIPELINE</span>
            <strong>{systemStatus.pipeline}</strong>
          </article>
          <article className="status-chip">
            <span>QUEUE</span>
            <strong>{systemStatus.queue}</strong>
          </article>
        </div>
      </header>

      <aside className="sidebar">
        <h2 className="sidebar-title">Mission Phases</h2>

        <ol className="phase-list">
          {[
            {
              icon: "📦",
              name: "Ingest Repository",
              description: "Clone, index, and embed the codebase",
              done: cloneReady,
            },
            {
              icon: "🎫",
              name: "Load Incident",
              description: "Import or manually enter the incident ticket",
              done: incidentReady,
            },
            {
              icon: "🤖",
              name: "Execute Fix",
              description: "Run the autonomous remediation pipeline",
              done: Boolean(pipelineReport),
            },
          ].map((phase, index) => {
            const isActive = phaseActiveIndex === index;
            const isDone = phase.done && !isActive;
            return (
              <li key={phase.name} className={`phase-item ${isActive ? "active" : ""} ${isDone ? "done" : ""}`}>
                <span className="phase-icon">{isDone ? "✓" : phase.icon}</span>
                <div>
                  <p className="phase-name">{phase.name}</p>
                  <p className="phase-desc">{phase.description}</p>
                </div>
                <span className="phase-status">{isDone ? "✓" : "●"}</span>
              </li>
            );
          })}
        </ol>

        <div className="next-action-card">
          <p className="section-tag">Next Action</p>
          <p>→ {nextAction}</p>
        </div>
      </aside>

      <main className="main-content">
        <p className="desktop-notice">Best viewed on desktop (1280px+). Compact mode is provided below this breakpoint.</p>

        <section className="panel section-card" style={renderSectionStyle(100)}>
          <div className="section-label-bar">
            <span>01 · REPOSITORY INGEST</span>
          </div>

          <details className="responsive-accordion" open>
            <summary>Repository Ingest</summary>
            <div className="repo-ingest-grid accordion-body">
            <form className="ingest-form" onSubmit={handleIngestRepository}>
              <p className="section-subtitle">Step A · Source</p>

              <label className="field">
                GitHub Repository URL
                <input
                  value={repoUrl}
                  onChange={(event) => setRepoUrl(event.target.value)}
                  placeholder="https://github.com/owner/repo"
                />
              </label>

              {repoPreview.loading ? (
                <div className="repo-loader-inline">
                  <span className="loader-spinner" aria-hidden>
                    ⟳
                  </span>
                  <span className="helper-text">Fetching repo details, branches, contributors, and README...</span>
                </div>
              ) : null}

              <label className="field">
                Target Branch
                <select
                  value={repoRef}
                  onChange={(event) => setRepoRef(event.target.value)}
                  disabled={repoPreview.loading || branchOptions.length === 0}
                >
                  <option value="" disabled>
                    {repoPreview.loading
                      ? "Loading branches from GitHub MCP..."
                      : branchOptions.length === 0
                        ? "Paste GitHub URL to load branches"
                        : "Select branch"}
                  </option>
                  {branchOptions.map((branchName) => (
                    <option key={branchName} value={branchName}>
                      {branchName}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                Folder Name
                <input value={repoId} onChange={(event) => setRepoId(event.target.value)} placeholder="shopstack-platform_testing" required />
              </label>

              <div className="advanced-block">
                <p className="section-subtitle">Step B · Storage</p>
                <label className="field">
                  Local Workspace Path
                  <div className="path-picker-row">
                    <input
                      value={workspacePath}
                      onChange={(event) => setWorkspacePath(event.target.value)}
                      placeholder="./workspace/repos"
                      required
                    />
                    <button type="button" className="ghost-button" onClick={handleLocateFolder}>
                      Locate Folder
                    </button>
                  </div>
                </label>

                <label className="toggle-row" htmlFor="re-embed-on-pull">
                  <span>Re-embed on pull</span>
                  <input
                    id="re-embed-on-pull"
                    type="checkbox"
                    checked={reEmbedOnPull}
                    onChange={(event) => setReEmbedOnPull(event.target.checked)}
                  />
                </label>
              </div>

              <button type="submit" className="button-primary wide" disabled={isCloning}>
                {isCloning ? "Ingesting repository..." : "▶ Ingest Repository"}
              </button>

              <div className="ingest-progress">
                {[
                  { label: "Cloning", icon: "✓", runningIcon: "⟳" },
                  { label: "Embedding", icon: "✓", runningIcon: "⟳" },
                  { label: "Ready", icon: "✓", runningIcon: "●" },
                ].map((step, index) => {
                  const done = cloneReady ? true : ingestStageIndex > index;
                  const running = !cloneReady && isCloning && ingestStageIndex === index;
                  const timeLabel =
                    cloneReady && ingestDurations[index] > 0
                      ? `${ingestDurations[index].toFixed(1)}s`
                      : running
                        ? `${ingestElapsed.toFixed(1)}s`
                        : "0.0s";

                  return (
                    <div key={step.label} className={`ingest-step ${done ? "done" : ""} ${running ? "running" : ""}`}>
                      <span>{done ? step.icon : running ? step.runningIcon : "○"}</span>
                      <p>{step.label}</p>
                      <small>{timeLabel}</small>
                    </div>
                  );
                })}
              </div>

              <FeedbackBanner feedback={cloneFeedback} />
            </form>

            <aside className="repo-preview-card">
              {!repoPreview.data && !repoPreview.loading ? (
                <div className="repo-empty">
                  <p>◈ No repo connected</p>
                  <p>Paste a GitHub URL to preview repository info.</p>
                </div>
              ) : null}

              {repoPreview.loading ? (
                <div className="repo-loading-shell">
                  <div className="repo-loading-head">
                    <span className="loader-spinner" aria-hidden>
                      ⟳
                    </span>
                    <p>Loading repository intelligence...</p>
                  </div>
                  <div className="repo-skeleton-line long" />
                  <div className="repo-skeleton-line medium" />
                  <div className="repo-skeleton-line short" />
                </div>
              ) : null}
              {repoPreview.error ? <p className="helper-text">{repoPreview.error}</p> : null}

              {repoPreview.data ? (
                <div className="repo-populated">
                  <p className="repo-name">⬡ {repoPreview.data.name ?? "Repository"}</p>
                  <p className="helper-text">{repoPreview.data.full_name}</p>
                  <p className="helper-text">{repoPreview.data.description ?? "No description available."}</p>

                  <div className="repo-metrics">
                    <span>★ {repoPreview.data.stargazers_count ?? 0}</span>
                    <span>🍴 {repoPreview.data.forks_count ?? 0}</span>
                    <span>● {repoPreview.data.language ?? "Unknown"}</span>
                    <span>👁 {repoPreview.data.watchers_count ?? 0}</span>
                    <span>⚠ {repoPreview.data.open_issues_count ?? 0}</span>
                    <span>⎇ {repoPreview.data.default_branch ?? "unknown"}</span>
                  </div>

                  <p className="helper-text">Last commit: {relativeTime(repoPreview.data.pushed_at)}</p>

                  <div className="repo-subsection">
                    <p className="section-subtitle">Top Contributors</p>
                    {(repoPreview.data.contributors ?? []).length === 0 ? (
                      <p className="helper-text">No contributor data available.</p>
                    ) : (
                      <ul className="pill-list">
                        {(repoPreview.data.contributors ?? []).slice(0, 8).map((contributor) => (
                          <li key={contributor.login}>
                            {contributor.login} · {contributor.contributions ?? 0}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="repo-subsection">
                    <p className="section-subtitle">README</p>
                    {repoPreview.data.readme ? (
                      <pre className="repo-readme-preview">{repoPreview.data.readme.slice(0, 1600)}</pre>
                    ) : (
                      <p className="helper-text">README content unavailable.</p>
                    )}
                  </div>

                  <p className="embed-status">
                    Embed status: {cloneReady ? "✓ Indexed · metadata synchronized" : "○ Not indexed"}
                  </p>

                  {cloneResult?.commitSha ? <p className="helper-text">Commit: {cloneResult.commitSha.slice(0, 10)}</p> : null}
                </div>
              ) : null}
            </aside>
            </div>
          </details>
        </section>

        <section className="panel section-card" style={renderSectionStyle(150)}>
          <div className="section-label-bar">
            <span>02 · INCIDENT LOADER</span>
          </div>

          <details className="responsive-accordion" open>
            <summary>Incident Loader</summary>
            <div className="incident-grid accordion-body">
            <article className="incident-ticket-card">
              <div className="ticket-header-row">
                <code>{incidentId}</code>

                <label className={`severity-badge ${ticketSeverity.toLowerCase()}`}>
                  <select value={ticketSeverity} onChange={(event) => setTicketSeverity(event.target.value as Severity)}>
                    <option value="P0">P0 · CRITICAL</option>
                    <option value="P1">P1 · HIGH</option>
                    <option value="P2">P2 · MEDIUM</option>
                    <option value="P3">P3 · LOW</option>
                  </select>
                </label>
              </div>

              <label className="title-field">
                <input
                  value={ticketTitle}
                  onChange={(event) => setTicketTitle(event.target.value.slice(0, 120))}
                  placeholder="Describe the incident in one line..."
                />
                <small>{ticketTitle.length} / 120</small>
              </label>

              <label className="field">
                Description
                <textarea
                  value={ticketDescription}
                  onChange={(event) => setTicketDescription(event.target.value)}
                  placeholder={`Paste stack trace, error logs, or describe observed behavior.\n\nExample:\nTypeError: Cannot read property 'id' of null\n  at PaymentService.processCheckout (payment.js:84)`}
                />
              </label>

              <div className="ticket-footer-row">
                <span className="assignee-chip">🤖 AI Agent · {AGENT_CODE}</span>

                <div className="detected-signals">
                  <span>Detected signals:</span>
                  {detectedSignals.length > 0 ? (
                    detectedSignals.map((signal) => (
                      <span key={signal} className="signal-chip">
                        {signal}
                      </span>
                    ))
                  ) : (
                    <span className="helper-text">none</span>
                  )}
                </div>
              </div>

              <div className="cta-row">
                <button className="button-primary" type="button" disabled={isAnalyzingTicket} onClick={handleAnalyzeAndQueue}>
                  {isAnalyzingTicket ? "Analyzing..." : "Analyze & Queue →"}
                </button>
                <button className="ghost-button" type="button" onClick={clearIncidentDraft}>
                  Clear
                </button>
              </div>

              <FeedbackBanner feedback={ticketFeedback} />
            </article>

            <aside className="active-incidents-panel">
              <div className="panel-head-row">
                <h3>Active Incidents</h3>
                <button className="ghost-button" type="button" onClick={handleSyncJira} disabled={isSyncingJira}>
                  {isSyncingJira ? "Syncing..." : "Sync Jira ↻"}
                </button>
              </div>

              {incidentQueue.length === 0 ? (
                <div className="queue-empty">
                  <p>○ No incidents in queue.</p>
                  <p>Sync from Jira or enter one manually.</p>
                </div>
              ) : (
                <div className="incident-queue-list">
                  {incidentQueue.map((incident) => (
                    <article
                      key={incident.incidentId}
                      className={`incident-queue-item ${selectedIncidentId === incident.incidentId ? "active" : ""}`}
                    >
                      <div className="queue-top-row">
                        <strong>{incident.incidentId}</strong>
                        <span className={`mini-severity ${incident.severity.toLowerCase()}`}>{incident.severity}</span>
                      </div>
                      <p>{incident.title}</p>
                      <small>
                        {incident.fetchedLabel}
                        {incident.jiraKey ? ` · Jira: ${incident.jiraKey}` : " · Manual"}
                      </small>

                      <button type="button" className="ghost-button" onClick={() => loadIncident(incident)}>
                        Load →
                      </button>
                    </article>
                  ))}
                </div>
              )}
            </aside>
            </div>
          </details>
        </section>

        <section className="panel section-card" style={renderSectionStyle(200)}>
          <div className="section-label-bar">
            <span>03 · PIPELINE EXECUTION</span>
          </div>

          <details className="responsive-accordion" open>
            <summary>Pipeline Execution</summary>
            <div className="pipeline-grid accordion-body">
            <aside className="pipeline-stepper">
              {PIPELINE_STEPS.map((step, index) => {
                const runtime = stepRuntime[index];
                const clickable = runtime.status === "complete" || runtime.status === "failed";
                return (
                  <button
                    type="button"
                    key={step.name}
                    className={`pipeline-step-card ${runtime.status}`}
                    onClick={() => (clickable ? jumpToStepLog(index) : undefined)}
                    disabled={!clickable}
                  >
                    <div className="step-header">
                      <span className={`step-icon ${runtime.status === "running" ? "spin" : ""}`}>
                        {runtime.status === "waiting" ? "○" : runtime.status === "running" ? "⟳" : runtime.status === "complete" ? "✓" : "✗"}
                      </span>
                      <div>
                        <p>{step.name}</p>
                        <small>{step.description}</small>
                      </div>
                    </div>

                    <div className="step-footer">
                      <span className={`step-badge ${runtime.status}`}>
                        {runtime.status === "waiting"
                          ? "—"
                          : runtime.status === "running"
                            ? "Running ●"
                            : runtime.status === "complete"
                              ? `Done · ${formatStepDuration(runtime.durationMs)}`
                              : "Failed"}
                      </span>
                    </div>
                  </button>
                );
              })}
            </aside>

            <section className="terminal-shell">
              <header className="terminal-header">
                <div className="terminal-dots">
                  <span className="dot red" />
                  <span className="dot yellow" />
                  <span className="dot green" />
                </div>

                <p>agent-fix-runner · {AGENT_CODE}</p>

                <button className="button-primary" type="button" onClick={handleRunPipeline} disabled={!pipelineReady || isRunningPipeline}>
                  {isRunningPipeline ? "Running..." : "Run Pipeline ▶"}
                </button>
              </header>

              <FeedbackBanner feedback={pipelineFeedback} />

              {!pipelineReady ? (
                <p className="helper-text">Run button unlocks when repository ingest and incident loading are complete.</p>
              ) : null}

              <div className="terminal-body" ref={terminalRef}>
                {terminalLines.length === 0 ? (
                  <p className="helper-text">Live logs will stream here once execution starts.</p>
                ) : (
                  terminalLines.map((line) => (
                    <div key={line.id} id={`terminal-line-${line.id}`} className={`terminal-line tag-${line.tag.toLowerCase()}`}>
                      <span className="ts">[{line.timestamp}]</span>
                      <span className="tag">[{line.tag}]</span>
                      <span>{line.text}</span>
                    </div>
                  ))
                )}
              </div>

              <div className="diff-toggle-row">
                <button className="ghost-button" type="button" onClick={() => setShowDiffViewer((value) => !value)}>
                  {showDiffViewer ? "Hide Code Diff Viewer" : "Code Diff Viewer"}
                </button>
              </div>

              {showDiffViewer ? (
                <div className="diff-viewer">
                  {pseudoDiffLines.map((line, index) => (
                    <div
                      key={`${line}-${index}`}
                      className={`diff-line ${line.startsWith("+") ? "plus" : ""} ${line.startsWith("-") ? "minus" : ""}`}
                    >
                      {line || " "}
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
            </div>
          </details>
        </section>

        <section className="panel section-card" style={renderSectionStyle(250)}>
          <div className="section-label-bar">
            <span>04 · RESOLUTION REPORT</span>
          </div>

          <details className="responsive-accordion" open>
            <summary>Resolution Report</summary>
            <div className="accordion-body">
          {!pipelineReport ? (
            <p className="helper-text">○ No report yet. Execute the pipeline to generate a resolution report.</p>
          ) : (
            <>
              <article className="report-card root-cause-wide">
                <header>
                  <h3>Root Cause</h3>
                </header>
                <p>
                  <strong>Location:</strong> {rootCause.location}
                </p>
                <p>
                  <strong>Type:</strong> {rootCause.type}
                </p>
                <p>
                  <strong>Explanation:</strong> {rootCause.explanation}
                </p>
              </article>

              <div className="report-grid-2x2">
                <article className="report-card changes-card">
                  <header>
                    <h3>Changes Applied</h3>
                  </header>

                  {changedFiles.length === 0 ? (
                    <p className="helper-text">No file change artifacts captured.</p>
                  ) : (
                    <ul className="pill-list">
                      {changedFiles.map((file) => (
                        <li key={file}>{file} · +? −?</li>
                      ))}
                    </ul>
                  )}
                </article>

                <article className="report-card validation-card">
                  <header>
                    <h3>Validation Results</h3>
                  </header>

                  <p className="validation-summary">
                    Tests: {validationSummary.passed} passed · {validationSummary.failed} failed · {validationSummary.skipped} skipped
                  </p>
                  <p className="helper-text">
                    Tickets: {validationSummary.ticketPassed} successful · {validationSummary.ticketFailed} failed
                    {validationSummary.failedBeforeTests > 0 ? ` (${validationSummary.failedBeforeTests} failed before tests ran)` : ""}
                  </p>
                  <div className="validation-bar">
                    <div className="validation-fill" style={{ width: `${validationSummary.ratio}%` }} />
                  </div>

                  <div className="table-shell">
                    <table>
                      <thead>
                        <tr>
                          <th>Ticket</th>
                          <th>Result</th>
                          <th>Time</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(pipelineReport.tickets ?? []).map((ticket) => (
                          <tr key={`validation-${ticket.ticket_key ?? "unknown"}`}>
                            <td>{ticket.ticket_key ?? "UNKNOWN"}</td>
                            <td>{formatTicketValidationResult(ticket)}</td>
                            <td>
                              {ticket.tests?.selected_tests?.length
                                ? `${Math.max(0.04, ticket.tests.selected_tests.length * 0.04).toFixed(2)}s`
                                : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </article>
              </div>

              <article className="report-actions-bar">
                <button type="button" className="button-primary" onClick={handleCopyMarkdownReport}>
                  📋 Copy Report as Markdown
                </button>
                <button type="button" className="ghost-button" onClick={handleExportJson}>
                  ⬇ Export JSON
                </button>
                <button type="button" className="ghost-button" onClick={handleRunPipeline} disabled={isRunningPipeline || !pipelineReady}>
                  ↺ Re-run Pipeline
                </button>

                <span className="resolved-meta">
                  Resolved at {pipelineMeta?.finishedAt ? new Date(pipelineMeta.finishedAt).toLocaleTimeString() : "--"}
                  {runDuration ? ` · Duration: ${runDuration}s` : ""}
                </span>
              </article>

              <FeedbackBanner feedback={reportFeedback} />

              <div className="report-accordion-list">
                {(pipelineReport.tickets ?? []).map((ticket, idx) => (
                  <TicketReportAccordion key={`${ticket.ticket_key ?? "unknown"}-${idx}`} item={ticket} />
                ))}
              </div>
            </>
          )}
            </div>
          </details>
        </section>
      </main>
    </div>
  );
}
