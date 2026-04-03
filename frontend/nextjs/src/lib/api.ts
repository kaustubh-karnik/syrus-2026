import {
  CloneRepoPayload,
  CloneRepoResponse,
  GithubRepositoryOverview,
  JiraTicket,
  LastPipelineRunResponse,
} from "@/lib/types";
import { normalizeBaseUrl, safeToString } from "@/lib/utils";

export class ApiError extends Error {
  status?: number;
  details?: unknown;

  constructor(message: string, status?: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function parseError(response: Response): Promise<ApiError> {
  const details = await parseResponseBody(response);
  const fallbackText = safeToString(details) || "Backend request failed";
  return new ApiError(fallbackText, response.status, details);
}

export async function cloneRepository(
  baseUrl: string,
  payload: CloneRepoPayload,
): Promise<CloneRepoResponse> {
  const endpoint = `${normalizeBaseUrl(baseUrl)}/agent/clone-repo`;
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  return (await response.json()) as CloneRepoResponse;
}

export async function getTickets(baseUrl: string): Promise<JiraTicket[]> {
  const endpoint = `${normalizeBaseUrl(baseUrl)}/tickets`;
  const response = await fetch(endpoint);

  if (!response.ok) {
    throw await parseError(response);
  }

  return (await response.json()) as JiraTicket[];
}

export async function streamPipelineLogs(
  baseUrl: string,
  onLine: (line: string) => void,
): Promise<void> {
  const endpoint = `${normalizeBaseUrl(baseUrl)}/pipeline/solve-all-bugs`;
  const response = await fetch(endpoint, { method: "POST" });

  if (!response.ok) {
    throw await parseError(response);
  }

  if (!response.body) {
    throw new ApiError("Pipeline started but no response stream was provided");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      onLine(line);
    }
  }

  if (buffer) {
    onLine(buffer);
  }
}

export async function getLastPipelineRun(baseUrl: string): Promise<LastPipelineRunResponse> {
  const endpoint = `${normalizeBaseUrl(baseUrl)}/pipeline/last-run`;
  const response = await fetch(endpoint);

  if (!response.ok) {
    throw await parseError(response);
  }

  return (await response.json()) as LastPipelineRunResponse;
}

export async function stopPipelineRun(baseUrl: string): Promise<Record<string, unknown>> {
  const endpoint = `${normalizeBaseUrl(baseUrl)}/pipeline/stop`;
  const response = await fetch(endpoint, { method: "POST" });

  if (!response.ok) {
    throw await parseError(response);
  }

  return (await response.json()) as Record<string, unknown>;
}

export async function getGithubRepositoryOverview(
  baseUrl: string,
  owner: string,
  repo: string,
): Promise<GithubRepositoryOverview> {
  const endpoint = `${normalizeBaseUrl(baseUrl)}/github/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/overview`;
  const response = await fetch(endpoint);

  if (!response.ok) {
    throw await parseError(response);
  }

  return (await response.json()) as GithubRepositoryOverview;
}