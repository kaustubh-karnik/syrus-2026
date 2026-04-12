export interface CloneRepoPayload {
  repoUrl?: string;
  repoId: string;
  ref?: string;
  localStorageLocation?: string;
  autoRunDocker?: boolean;
}

export interface CloneRepoResponse {
  status?: string;
  operation?: string;
  localPath?: string;
  commitSha?: string;
  checkedOutRef?: string;
  ref?: string;
  [key: string]: unknown;
}

export interface JiraTicket {
  jira_key?: string;
  summary?: string;
  description?: unknown;
  priority?: string;
  status?: string;
}

export interface GithubBranch {
  name: string;
  protected?: boolean;
}

export interface GithubContributor {
  login: string;
  contributions?: number;
  html_url?: string | null;
}

export interface GithubRepositoryOverview {
  source?: string;
  owner: string;
  repo: string;
  name?: string;
  full_name?: string;
  description?: string | null;
  html_url?: string;
  stargazers_count?: number;
  forks_count?: number;
  watchers_count?: number;
  open_issues_count?: number;
  language?: string | null;
  default_branch?: string;
  pushed_at?: string;
  branches?: GithubBranch[];
  contributors?: GithubContributor[];
  readme?: string | null;
  tools?: string[];
}

export interface TestReport {
  passed?: boolean;
  selected_tests?: string[];
  passed_tests?: string[];
  failed_tests?: string[];
  test_plan_source?: string;
  commands?: string[][];
  pass_override_reason?: string | null;
  failure_reason?: string;
  test_output?: string;
  test_error?: string;
}

export interface ProviderAttemptReport {
  provider?: string;
  attempt?: number;
  success?: boolean;
  failure_type?: string;
  error?: string;
  elapsed_seconds?: number;
}

export interface PatchValidationReport {
  success?: boolean;
  status?: string;
  errors?: string[];
  validated_files?: string[];
  validated_edit_count?: number;
}

export interface RecoveryReport {
  decision?: string;
  reason?: string;
  failed_tests?: string[];
}

export interface TicketReport {
  ticket_key?: string;
  status?: string;
  result_category?: string;
  success?: boolean;
  attempt_count?: number;
  error?: string;
  failure_type?: string;
  blocked_reason?: string;
  providers_used?: string[];
  provider_attempts?: ProviderAttemptReport[];
  llm_failures?: Array<Record<string, unknown>>;
  patch_validation?: PatchValidationReport;
  recovery?: RecoveryReport;
  edit_reason?: string;
  edited_files?: string[];
  promoted_files?: string[];
  where_was_edited?: string[];
  edit_details?: Array<Record<string, unknown>>;
  tests?: TestReport;
}

export interface PipelineSummary {
  requested?: number;
  processed?: number;
  successful?: number;
  halted?: boolean;
  halt_reason?: string;
}

export interface PipelineReport {
  summary?: PipelineSummary;
  tickets?: TicketReport[];
  post_batch_validation?: Record<string, unknown>;
  post_batch_auto_repair?: Record<string, unknown>;
}

export interface LastPipelineRunResponse {
  status?: string;
  startedAt?: string;
  finishedAt?: string;
  exitCode?: number;
  logs?: string;
  report?: PipelineReport | null;
  [key: string]: unknown;
}
