"use client";

import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="landing-root">
      <nav className="landing-nav">
        <div className="landing-nav-container">
          <div className="landing-brand">
            <span className="landing-brand-icon">◈</span>
            <span className="landing-brand-text">MPM Build</span>
          </div>
          <div className="landing-nav-links">
            <a href="#features" className="landing-nav-link">Features</a>
            <a href="#how-it-works" className="landing-nav-link">How It Works</a>
            <a href="#technical" className="landing-nav-link">Technical</a>
            <Link href="/dashboard" className="landing-nav-cta">
              Launch App
            </Link>
          </div>
        </div>
      </nav>

      <section className="landing-hero">
        <div className="landing-hero-content">
          <div className="landing-hero-left">
            <p className="landing-hero-label">Autonomous Incident-to-Fix Engineering</p>
            <h1 className="landing-hero-title">
              <span>Analyze</span>
              <span>Fix</span>
              <span>Deploy</span>
            </h1>
            <p className="landing-hero-subtitle">
              Autonomous incident-to-fix engineering agent powered by multi-agent AI orchestration
            </p>
            <div className="landing-hero-actions">
              <Link href="/dashboard" className="landing-btn landing-btn-primary">
                Launch Dashboard
              </Link>
              <a href="#technical" className="landing-btn landing-btn-secondary">
                View Technical Docs
              </a>
            </div>
          </div>

          <div className="landing-hero-right">
            <div className="landing-hero-terminal">
              <div className="landing-terminal-header">
                <span className="landing-terminal-dot red"></span>
                <span className="landing-terminal-dot yellow"></span>
                <span className="landing-terminal-dot green"></span>
                <span className="landing-terminal-title">incident → fix</span>
              </div>
              <div className="landing-terminal-body">
                <div className="landing-terminal-line">
                  <span className="landing-terminal-prompt">$</span> mpm-build analyze INC-5001
                </div>
                <div className="landing-terminal-line">
                  <span className="landing-terminal-timestamp">[13:45:22]</span> <span className="landing-terminal-tag">[PARSE]</span> Analyzing NullPointerException in payment service
                </div>
                <div className="landing-terminal-line">
                  <span className="landing-terminal-timestamp">[13:45:28]</span> <span className="landing-terminal-tag">[ANALYZE]</span> Root cause identified: missing null check in line 142
                </div>
                <div className="landing-terminal-line">
                  <span className="landing-terminal-timestamp">[13:45:35]</span> <span className="landing-terminal-tag">[PATCH]</span> Generated fix: added defensive null check
                </div>
                <div className="landing-terminal-line">
                  <span className="landing-terminal-timestamp">[13:45:42]</span> <span className="landing-terminal-tag">[TEST]</span> Running 24 tests...
                </div>
                <div className="landing-terminal-line landing-terminal-success">
                  <span className="landing-terminal-timestamp">[13:45:51]</span> <span className="landing-terminal-tag">[REPORT]</span> ✓ Fix validated. PR ready for review.
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="landing-stats-bar">
        <div className="landing-stats-container">
          <div className="landing-stat">
            <div className="landing-stat-value">6</div>
            <div className="landing-stat-label">AI Agents</div>
          </div>
          <div className="landing-stat-divider"></div>
          <div className="landing-stat">
            <div className="landing-stat-value">&lt;3 min</div>
            <div className="landing-stat-label">MTTR</div>
          </div>
          <div className="landing-stat-divider"></div>
          <div className="landing-stat">
            <div className="landing-stat-value">100%</div>
            <div className="landing-stat-label">Autonomous</div>
          </div>
          <div className="landing-stat-divider"></div>
          <div className="landing-stat">
            <div className="landing-stat-value">Zero</div>
            <div className="landing-stat-label">Human Needed</div>
          </div>
        </div>
      </section>

      <section id="features" className="landing-features">
        <div className="landing-section-header">
          <h2>Capabilities</h2>
          <p>Everything a production incident needs</p>
        </div>
        <div className="landing-features-grid">
          <FeatureCard
            title="Incident Parsing"
            description="Understands tickets from Jira or Slack; extracts error type, affected component, environment, and relevant commits"
            icon="📋"
          />
          <FeatureCard
            title="Codebase Analysis"
            description="Detects logical errors, dependency conflicts, config issues, and maps stack traces to source"
            icon="🔍"
          />
          <FeatureCard
            title="Autonomous Fix"
            description="Applies targeted, explainable code or config changes without human guidance"
            icon="🔧"
          />
          <FeatureCard
            title="Knowledge Retrieval"
            description="Pulls relevant docs or known error references when root cause is unclear"
            icon="📚"
          />
          <FeatureCard
            title="Validation & Sandbox"
            description="Generates test cases, runs existing test suites, executes fix in isolated environment"
            icon="✓"
          />
          <FeatureCard
            title="Resolution Report"
            description="Produces root cause summary, files changed, confidence score, and risk assessment"
            icon="📊"
          />
        </div>
      </section>

      <section id="how-it-works" className="landing-steps">
        <div className="landing-section-header">
          <h2>How It Works</h2>
          <p>From incident to fix in three stages</p>
        </div>
        <div className="landing-steps-container">
          <StepCard
            number="1"
            title="Load Incident"
            description="Submit an incident ticket from Jira, Slack, or manual entry. The agent extracts context, error signals, and affected services."
          />
          <StepCard
            number="2"
            title="Execute Pipeline"
            description="6-step autonomous pipeline: parse ticket, search codebase, identify root cause, generate fix, validate in sandbox, compile report."
          />
          <StepCard
            number="3"
            title="Review & Merge"
            description="Reviewed fix with full traceability. Root cause, changes, tests—all documented. Auto-open PR or alert on Slack."
          />
        </div>
      </section>

      <section id="technical" className="landing-specs">
        <div className="landing-section-header">
          <h2>Technical Specifications</h2>
          <p>Built on proven enterprise tools</p>
        </div>
        <div className="landing-specs-grid">
          <div className="landing-specs-column">
            <div className="landing-specs-table">
              <div className="landing-specs-row">
                <span className="landing-specs-key">Pipeline Stages</span>
                <span className="landing-specs-value">6</span>
              </div>
              <div className="landing-specs-row">
                <span className="landing-specs-key">Sandbox Timeout</span>
                <span className="landing-specs-value">30 seconds</span>
              </div>
              <div className="landing-specs-row">
                <span className="landing-specs-key">Max Retries</span>
                <span className="landing-specs-value">3</span>
              </div>
              <div className="landing-specs-row">
                <span className="landing-specs-key">Supported Sources</span>
                <span className="landing-specs-value">Jira / Slack / Manual</span>
              </div>
              <div className="landing-specs-row">
                <span className="landing-specs-key">Concurrent Incidents</span>
                <span className="landing-specs-value">Unlimited</span>
              </div>
              <div className="landing-specs-row">
                <span className="landing-specs-key">Architecture</span>
                <span className="landing-specs-value">Stateless Agents</span>
              </div>
            </div>
          </div>
          <div className="landing-specs-column">
            <div className="landing-specs-code">
              <div className="landing-specs-code-header">
                Sample incident payload
              </div>
              <pre className="landing-specs-code-block">{`{
  "ticket": "INC-5001",
  "title": "Payment API 500 errors",
  "description": "Users unable to checkout...",
  "severity": "P0",
  "signals": ["500", "NullPointerException"],
  "service": "payment-service",
  "environment": "production"
}`}</pre>
            </div>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <div className="landing-footer-content">
          <div className="landing-footer-col">
            <h4>Team</h4>
            <p>MPM Build</p>
          </div>
          <div className="landing-footer-col">
            <h4>Institution</h4>
            <p>Vivekanand Education Society&apos;s Institute of Technology (VESIT)</p>
          </div>
          <div className="landing-footer-col">
            <h4>Event</h4>
            <p>CIPHER VELORA 1.0 Hackathon</p>
          </div>
          <div className="landing-footer-col">
            <h4>Links</h4>
            <Link href="/dashboard">Dashboard</Link>
          </div>
        </div>
        <div className="landing-footer-bottom">
          <p>&copy; 2025 MPM Build. Autonomous incident resolution.</p>
        </div>
      </footer>
    </div>
  );
}

function FeatureCard({
  title,
  description,
  icon,
}: {
  title: string;
  description: string;
  icon: string;
}) {
  return (
    <div className="landing-feature-card">
      <div className="landing-feature-icon">{icon}</div>
      <h3 className="landing-feature-title">{title}</h3>
      <p className="landing-feature-description">{description}</p>
    </div>
  );
}

function StepCard({
  number,
  title,
  description,
}: {
  number: string;
  title: string;
  description: string;
}) {
  return (
    <div className="landing-step-card">
      <div className="landing-step-number">{number}</div>
      <h3 className="landing-step-title">{title}</h3>
      <p className="landing-step-description">{description}</p>
    </div>
  );
}
