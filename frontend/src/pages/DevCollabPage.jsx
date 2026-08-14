import React, { useCallback, useEffect, useState } from "react";
import { GitBranch, AlertTriangle, Sparkles, Loader2, RefreshCw, GitCommit, Github, ExternalLink, FileSearch, ScanSearch, Brain, Award, Layers, Check, X, Clock, Undo2 } from "lucide-react";
import {
  getActiveSessions,
  listConflicts,
  simulateDemoConflict,
  suggestResolution,
  approveConflict,
  rejectConflict,
  deferConflict,
  undoConflictAction,
  listCommits,
  githubStatus,
  githubSync,
  repositoryDiscovery,
} from "../services/apiClient";
import { useLiveSocketContext } from "../context/LiveSocketContext";
import { useAppConfig } from "../context/AppConfigContext";
import RepoSubmitPanel from "../components/common/RepoSubmitPanel";
import { formatLiveTime } from "../utils/datetime";

const EVENTS_THAT_REFRESH = ["edit_session_started", "edit_session_ended", "conflict_detected", "conflict_resolved", "conflict_suggestion_ready", "conflict_updated", "repo_scanned"];

function riskColor(score) {
  if (score >= 70) return "bg-red-500";
  if (score >= 40) return "bg-accent-warning";
  return "bg-accent-success";
}

export default function DevCollabPage() {
  const [sessions, setSessions] = useState([]);
  const [conflicts, setConflicts] = useState([]);
  const [commits, setCommits] = useState([]);
  const [error, setError] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [simulating, setSimulating] = useState(false);
  const [suggestingId, setSuggestingId] = useState(null);
  const [hitlBusy, setHitlBusy] = useState(null);
  const [github, setGithub] = useState({ configured: false, repo: null });
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const [discovering, setDiscovering] = useState(false);
  const [discoveryResult, setDiscoveryResult] = useState(null);
  const { lastEvent } = useLiveSocketContext();
  const { simulateUiEnabled } = useAppConfig();

  const loadData = useCallback(() => {
    Promise.all([getActiveSessions(), listConflicts(), listCommits()])
      .then(([sessionsRes, conflictsRes, commitsRes]) => {
        setSessions(sessionsRes.data);
        setConflicts(conflictsRes.data);
        setCommits(commitsRes.data);
        setError(false);
        setErrorMessage("");
      })
      .catch((err) => {
        setError(true);
        setErrorMessage(
          err.code === "ECONNABORTED"
            ? "Request timed out — the backend may still be processing. Try Refresh."
            : "Backend not reachable — make sure the FastAPI server is running on port 8000."
        );
      });
  }, []);

  useEffect(() => {
    loadData();
    githubStatus().then((res) => setGithub(res.data)).catch(() => {});
  }, [loadData]);

  useEffect(() => {
    if (lastEvent && EVENTS_THAT_REFRESH.includes(lastEvent.type)) {
      loadData();
    }
  }, [lastEvent, loadData]);

  async function handleSimulate() {
    setSimulating(true);
    setError(false);
    setErrorMessage("");
    try {
      await simulateDemoConflict();
      loadData();
    } catch (err) {
      setError(true);
      if (err.code === "ECONNABORTED") {
        setErrorMessage(
          "Simulate Conflict timed out — LLM and Slack alerts can take 15–20 seconds. Try again or click Refresh."
        );
      } else if (err.response?.data?.detail) {
        setErrorMessage(String(err.response.data.detail));
      } else {
        setErrorMessage(
          "Backend not reachable — make sure the FastAPI server is running on port 8000."
        );
      }
    } finally {
      setSimulating(false);
    }
  }

  async function handleGithubSync() {
    setSyncing(true);
    setSyncResult(null);
    try {
      const res = await githubSync();
      setSyncResult(res.data);
      loadData();
    } catch (err) {
      let message = "Unknown error.";
      if (err.code === "ECONNABORTED") {
        message = "Timed out — GitHub is taking a while to respond (try again, or check your connection).";
      } else if (err.response?.data?.detail) {
        message = err.response.data.detail;
      } else if (err.message) {
        message = err.message;
      }
      setSyncResult({ synced: false, error: message });
    } finally {
      setSyncing(false);
    }
  }

  async function handleDiscovery() {
    setDiscovering(true);
    setDiscoveryResult(null);
    try {
      const res = await repositoryDiscovery({});
      setDiscoveryResult(res.data);
    } catch (err) {
      setDiscoveryResult({ error: err.response?.data?.detail || err.message });
    } finally {
      setDiscovering(false);
    }
  }

  async function handleSuggest(conflictId) {
    setSuggestingId(conflictId);
    try {
      await suggestResolution(conflictId);
      loadData();
    } catch {
      // Non-fatal: leave the conflict card as-is if the suggestion call fails.
    } finally {
      setSuggestingId(null);
    }
  }

  async function handleHitl(conflictId, action) {
    setHitlBusy(`${conflictId}-${action}`);
    try {
      const actions = {
        approve: approveConflict,
        reject: rejectConflict,
        defer: deferConflict,
        undo: undoConflictAction,
      };
      await actions[action](conflictId);
      loadData();
    } catch {
      // Non-fatal: card stays as-is if HITL action fails.
    } finally {
      setHitlBusy(null);
    }
  }

  return (
    <div className="space-y-4 p-6">
      <RepoSubmitPanel onScanned={loadData} />

        {/* Enterprise Repository Discovery */}
        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-ink-primary flex items-center gap-2">
              <ScanSearch size={16} className="text-accent-devcollab" />
              Repository Discovery (Phase 1)
            </h2>
            <button
              onClick={handleDiscovery}
              disabled={discovering}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-accent-devcollab/15 text-accent-devcollab border border-accent-devcollab/30 hover:bg-accent-devcollab/25 transition-colors disabled:opacity-50"
            >
              {discovering ? <Loader2 size={13} className="animate-spin" /> : <ScanSearch size={13} />}
              Scan Repository
            </button>
          </div>
          <p className="text-xs text-ink-muted mb-2">
            Real AST scan of backend/app and frontend/src — indexes functions, classes, complexity.
          </p>
          {discoveryResult && !discoveryResult.error && (
            <div className="text-xs rounded-lg px-3 py-2 bg-accent-success/10 text-accent-success">
              Indexed {discoveryResult.context?.symbols_indexed ?? 0} symbols across{" "}
              {discoveryResult.context?.files_scanned ?? 0} files.
            </div>
          )}
          {discoveryResult?.error && (
            <div className="text-xs rounded-lg px-3 py-2 bg-accent-warning/10 text-accent-warning">
              {discoveryResult.error}
            </div>
          )}
        </div>

        {/* Real GitHub Integration panel */}
        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-ink-primary flex items-center gap-2">
              <Github size={16} className="text-ink-primary" />
              Real GitHub Integration
            </h2>
            <button
              onClick={handleGithubSync}
              disabled={syncing || !github.configured}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-ink-primary/10 text-ink-primary border border-base-border hover:bg-ink-primary/20 transition-colors disabled:opacity-50"
            >
              {syncing ? <Loader2 size={13} className="animate-spin" /> : <Github size={13} />}
              Sync with GitHub
            </button>
          </div>

          {github.configured ? (
            <div className="text-xs text-ink-faint mb-2 space-y-1">
              <p>
                Connected to real repository: <span className="font-mono text-ink-secondary">{github.repo}</span>.
                Manual sync or GitHub webhook for instant PR updates.
              </p>
              {github.webhook_url && (
                <p>
                  Webhook URL:{" "}
                  <span className="font-mono text-ink-secondary break-all">{github.webhook_url}</span>
                  {github.webhook_secret_configured ? (
                    <span className="text-accent-success ml-1">(secret configured)</span>
                  ) : (
                    <span className="text-ink-muted ml-1">(set GITHUB_WEBHOOK_SECRET in .env for production)</span>
                  )}
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-ink-muted mb-2">
              Not connected yet. Add <span className="font-mono">GITHUB_TOKEN</span>,{" "}
              <span className="font-mono">GITHUB_REPO_OWNER</span> and <span className="font-mono">GITHUB_REPO_NAME</span> to
              your backend <span className="font-mono">.env</span> file, then restart the server.
            </p>
          )}

          {syncResult && (
            <div className={`text-xs rounded-lg px-3 py-2 mt-2 ${syncResult.synced ? "bg-accent-success/10 text-accent-success" : "bg-accent-warning/10 text-accent-warning"}`}>
              {syncResult.synced
                ? `Checked ${syncResult.pull_requests_checked} open PR(s) — found ${syncResult.conflicts_found} new conflict(s)` +
                  (syncResult.conflicts_already_known ? `, ${syncResult.conflicts_already_known} already known.` : ".")
                : `Could not sync: ${syncResult.error}`}
            </div>
          )}
        </div>

        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-ink-primary flex items-center gap-2">
              <GitBranch size={16} className="text-accent-devcollab" />
              Live Editing Map
            </h2>
            <div className="flex items-center gap-2">
              <button
                onClick={loadData}
                className="p-1.5 rounded-lg border border-base-border text-ink-muted hover:text-ink-primary transition-colors"
                title="Refresh"
              >
                <RefreshCw size={14} />
              </button>
              {simulateUiEnabled && (
                <button
                  onClick={handleSimulate}
                  disabled={simulating}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-accent-devcollab/15 text-accent-devcollab border border-accent-devcollab/30 hover:bg-accent-devcollab/25 transition-colors disabled:opacity-50"
                >
                  {simulating ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                  Simulate Conflict
                </button>
              )}
            </div>
          </div>

          {error && (
            <p className="text-xs text-ink-muted">
              {errorMessage || "Backend not reachable — make sure the FastAPI server is running on port 8000."}
            </p>
          )}

          {!error && sessions.length === 0 && (
            <p className="text-xs text-ink-muted">
              Connect GitHub repo and click <span className="text-ink-primary">Sync with GitHub</span> to see live conflicts and edit sessions from open PRs.
            </p>
          )}

          <div className="space-y-2">
            {sessions.map((s) => (
              <div
                key={s.session_id}
                className="flex items-center justify-between text-xs bg-base-bg border border-base-border rounded-lg px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: s.avatar_color }} />
                  <span className="text-ink-primary font-medium">{s.developer_name}</span>
                  <span className="text-ink-muted font-mono">{s.file_path} → {s.function_name}</span>
                </div>
                <span className="text-ink-faint">
                  {formatLiveTime(s.started_at)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <h2 className="text-sm font-semibold text-ink-primary mb-3 flex items-center gap-2">
            <AlertTriangle size={16} className="text-accent-warning" />
            Predicted Conflicts
          </h2>

          {!error && conflicts.length === 0 && (
            <p className="text-xs text-ink-muted">No conflicts predicted yet.</p>
          )}

          <div className="space-y-3">
            {conflicts.map((c) => (
              <div key={c.id} className="border border-base-border rounded-lg px-3 py-3 bg-base-bg">
                <div className="flex items-center justify-between text-xs mb-2">
                  <span className="text-ink-primary font-medium">
                    {c.dev_a} <span className="text-ink-faint">&</span> {c.dev_b}
                  </span>
                  <div className="flex items-center gap-1.5">
                    {c.source === "github" && (
                      <span className="flex items-center gap-1 uppercase tracking-wide text-[10px] px-2 py-0.5 rounded-full bg-ink-primary/10 text-ink-primary">
                        <Github size={10} /> Real
                      </span>
                    )}
                    <span
                      className={`uppercase tracking-wide text-[10px] px-2 py-0.5 rounded-full ${
                        c.status === "resolved" ? "bg-accent-success/15 text-accent-success" : "bg-accent-warning/15 text-accent-warning"
                      }`}
                    >
                      {c.status}
                    </span>
                    {c.approval_status && (
                      <span className="uppercase tracking-wide text-[10px] px-2 py-0.5 rounded-full bg-accent-devcollab/15 text-accent-devcollab">
                        {c.approval_status.replace(/_/g, " ")}
                      </span>
                    )}
                  </div>
                </div>
                <p className="text-xs text-ink-muted font-mono mb-2">
                  {c.file_path} → {c.function_name}
                </p>

                <div className="flex items-center gap-2 mb-2">
                  <div className="flex-1 h-1.5 rounded-full bg-base-border overflow-hidden">
                    <div className={`h-full ${riskColor(c.risk_score)}`} style={{ width: `${c.risk_score}%` }} />
                  </div>
                  <span className="text-[10px] text-ink-muted w-10 text-right">{c.risk_score}%</span>
                </div>

                {c.source_url && (
                  <a
                    href={c.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-[11px] text-accent-devcollab hover:underline mb-2"
                  >
                    <ExternalLink size={11} /> View on GitHub
                  </a>
                )}

                {c.discovery_context && (
                  <div className="mb-2 rounded-lg bg-accent-devcollab/5 border border-accent-devcollab/20 px-2.5 py-2">
                    <p className="text-[10px] uppercase tracking-wide text-accent-devcollab font-medium mb-1 flex items-center gap-1">
                      <ScanSearch size={11} />
                      Repository Discovery
                    </p>
                    <p className="text-xs text-ink-secondary">
                      {c.discovery_context.symbols_indexed} symbols indexed
                      {c.discovery_context.target_symbol && (
                        <> — target: {c.discovery_context.target_symbol.name} (complexity {c.discovery_context.target_symbol.complexity})</>
                      )}
                    </p>
                  </div>
                )}

                {c.semantic_analysis && (
                  <div className="mb-2 rounded-lg bg-purple-500/5 border border-purple-500/20 px-2.5 py-2">
                    <p className="text-[10px] uppercase tracking-wide text-purple-400 font-medium mb-1 flex items-center gap-1">
                      <Brain size={11} />
                      Semantic Analysis — {c.semantic_analysis.conflict_type} ({c.semantic_analysis.semantic_risk_score}%)
                    </p>
                    <p className="text-xs text-ink-secondary leading-relaxed">
                      {c.semantic_analysis.analysis_text}
                    </p>
                  </div>
                )}

                {c.quality_report && (
                  <div className="mb-2 rounded-lg bg-emerald-500/5 border border-emerald-500/20 px-2.5 py-2">
                    <p className="text-[10px] uppercase tracking-wide text-emerald-400 font-medium mb-1 flex items-center gap-1">
                      <Award size={11} />
                      Quality Grade {c.quality_report.grade} — {c.quality_report.quality_score}/100
                    </p>
                    <p className="text-xs text-ink-secondary leading-relaxed">
                      {c.quality_report.report_text}
                    </p>
                  </div>
                )}

                {c.code_review_notes && (
                  <div className="mb-2 rounded-lg bg-accent-warning/5 border border-accent-warning/20 px-2.5 py-2">
                    <p className="text-[10px] uppercase tracking-wide text-accent-warning font-medium mb-1 flex items-center gap-1">
                      <FileSearch size={11} />
                      Code Review Agent
                    </p>
                    <p className="text-xs text-ink-secondary leading-relaxed">
                      {c.code_review_notes}
                    </p>
                  </div>
                )}

                {c.resolution_options && c.resolution_options.length > 0 && (
                  <div className="mt-2 mb-2 rounded-lg bg-base-bg border border-base-border px-2.5 py-2">
                    <p className="text-[10px] uppercase tracking-wide text-ink-muted font-medium mb-1.5 flex items-center gap-1">
                      <Layers size={11} />
                      Resolution Synthesizer — {c.resolution_options.length} strategies
                    </p>
                    <div className="space-y-1">
                      {c.resolution_options.map((opt, i) => (
                        <div key={i} className="text-[11px] text-ink-secondary flex justify-between gap-2">
                          <span className="truncate">{opt.strategy.replace(/_/g, " ")}</span>
                          <span className="text-ink-faint shrink-0">score {opt.score}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {c.ai_suggestion ? (
                  <div className="mt-2">
                    <p className="text-[10px] uppercase tracking-wide text-accent-devcollab font-medium mb-1 flex items-center gap-1">
                      <Sparkles size={11} />
                      Resolution Suggestion Agent
                    </p>
                    <p className="text-xs text-ink-secondary leading-relaxed border-l-2 border-accent-devcollab pl-2">
                      {c.ai_suggestion}
                    </p>
                    {c.approval_status === "pending_approval" && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          onClick={() => handleHitl(c.id, "approve")}
                          disabled={!!hitlBusy}
                          className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md bg-accent-success/15 text-accent-success hover:bg-accent-success/25 transition-colors disabled:opacity-50"
                        >
                          {hitlBusy === `${c.id}-approve` ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                          Approve
                        </button>
                        <button
                          onClick={() => handleHitl(c.id, "reject")}
                          disabled={!!hitlBusy}
                          className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors disabled:opacity-50"
                        >
                          {hitlBusy === `${c.id}-reject` ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />}
                          Reject
                        </button>
                        <button
                          onClick={() => handleHitl(c.id, "defer")}
                          disabled={!!hitlBusy}
                          className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md bg-accent-warning/15 text-accent-warning hover:bg-accent-warning/25 transition-colors disabled:opacity-50"
                        >
                          {hitlBusy === `${c.id}-defer` ? <Loader2 size={12} className="animate-spin" /> : <Clock size={12} />}
                          Resolve Later
                        </button>
                      </div>
                    )}
                    {["approved", "rejected", "deferred"].includes(c.approval_status) && (
                      <button
                        onClick={() => handleHitl(c.id, "undo")}
                        disabled={!!hitlBusy}
                        className="mt-2 flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md bg-base-border/50 text-ink-muted hover:bg-base-border transition-colors disabled:opacity-50"
                      >
                        {hitlBusy === `${c.id}-undo` ? <Loader2 size={12} className="animate-spin" /> : <Undo2 size={12} />}
                        Undo last action
                      </button>
                    )}
                  </div>
                ) : (
                  <button
                    onClick={() => handleSuggest(c.id)}
                    disabled={suggestingId === c.id}
                    className="flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-md bg-accent-devcollab/15 text-accent-devcollab hover:bg-accent-devcollab/25 transition-colors disabled:opacity-50"
                  >
                    {suggestingId === c.id ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                    Get AI Suggestion
                  </button>
                )}

                {c.resolved_by_name && (
                  <p className="text-[11px] text-accent-success mt-2">
                    Resolved by {c.resolved_by_name}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <h2 className="text-sm font-semibold text-ink-primary mb-3 flex items-center gap-2">
            <GitCommit size={16} className="text-ink-muted" />
            Recent Commits
          </h2>
          <p className="text-xs text-ink-faint mb-3">
            Created automatically when a conflict is resolved — this history is what the
            AIOps module later searches to link production incidents back to risky merges.
          </p>

          {!error && commits.length === 0 && (
            <p className="text-xs text-ink-muted">No commits yet. Resolve a conflict above to create one.</p>
          )}

          <div className="space-y-1.5">
            {commits.map((c) => (
              <div key={c.id} className="flex items-center justify-between text-xs bg-base-bg border border-base-border rounded-lg px-3 py-2">
                <span className="font-mono text-ink-muted">{c.commit_hash}</span>
                <span className="text-ink-secondary flex-1 mx-3 truncate">{c.message}</span>
                <span className="text-ink-faint">{c.developer_name}</span>
              </div>
            ))}
          </div>
        </div>
    </div>
  );
}
