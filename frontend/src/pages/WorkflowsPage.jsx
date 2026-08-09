import React, { useCallback, useEffect, useState } from "react";
import { GitBranch, Play, Loader2, RefreshCw, CheckCircle, Clock, XCircle, Undo2 } from "lucide-react";
import {
  listWorkflowDefinitions,
  startWorkflow,
  listWorkflowRuns,
  getWorkflowTimeline,
  resumeWorkflow,
  cancelWorkflow,
  simulateDemoConflict,
  listConflicts,
} from "../services/apiClient";
import { useLiveSocketContext } from "../context/LiveSocketContext";
import { useAppConfig } from "../context/AppConfigContext";

const statusColor = {
  running: "text-accent-devcollab",
  waiting_hitl: "text-accent-warning",
  completed: "text-accent-success",
  failed: "text-red-400",
  cancelled: "text-ink-muted",
};

export default function WorkflowsPage() {
  const [definitions, setDefinitions] = useState([]);
  const [runs, setRuns] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");
  const { lastEvent } = useLiveSocketContext();
  const { simulateEnabled } = useAppConfig();

  const load = useCallback(async () => {
    try {
      const [defRes, runRes] = await Promise.all([
        listWorkflowDefinitions(),
        listWorkflowRuns(),
      ]);
      setDefinitions(defRes.data);
      setRuns(runRes.data);
      setError("");
    } catch {
      setError("Could not load workflows.");
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (lastEvent?.type?.startsWith("workflow_")) load();
  }, [lastEvent, load]);

  async function loadTimeline(runId) {
    setSelectedRunId(runId);
    try {
      const res = await getWorkflowTimeline(runId);
      setTimeline(res.data);
    } catch {
      setTimeline([]);
    }
  }

  async function handleStart(templateKey) {
    setBusy(templateKey);
    setError("");
    try {
      let context = {};
      if (templateKey === "dev-conflict-resolution" || templateKey === "full-sdlc-bridge") {
        let conflicts = (await listConflicts()).data;
        if (!conflicts.length && simulateEnabled) {
          await simulateDemoConflict();
          conflicts = (await listConflicts()).data;
        }
        if (!conflicts.length) {
          throw new Error(
            simulateEnabled
              ? "No conflicts available."
              : "No conflicts available. Sync with GitHub or resolve a real conflict first."
          );
        }
        context = { conflict_id: conflicts[0].id };
      }
      const res = await startWorkflow(templateKey, context);
      await load();
      await loadTimeline(res.data.id);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Failed to start workflow.");
    } finally {
      setBusy(null);
    }
  }

  async function handleResume(runId) {
    setBusy(`resume-${runId}`);
    try {
      await resumeWorkflow(runId);
      await load();
      await loadTimeline(runId);
    } catch (err) {
      setError(err.response?.data?.detail || "Resume failed.");
    } finally {
      setBusy(null);
    }
  }

  async function handleCancel(runId) {
    setBusy(`cancel-${runId}`);
    try {
      await cancelWorkflow(runId);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Cancel failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="p-6 space-y-4 max-w-6xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-base font-semibold text-ink-primary flex items-center gap-2">
            <GitBranch size={18} className="text-accent-devcollab" />
            Workflow Orchestration
          </h2>
          <p className="text-xs text-ink-muted mt-1">
            Multi-step agent pipelines with HITL gates, retries, and live step timeline.
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-base-border text-ink-muted hover:text-ink-primary"
        >
          <RefreshCw size={13} />
          Refresh
        </button>
      </div>

      {error && (
        <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{error}</p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {definitions.map((def) => (
          <div key={def.template_key} className="bg-base-surface border border-base-border rounded-xl p-4">
            <h3 className="text-sm font-semibold text-ink-primary">{def.name}</h3>
            <p className="text-xs text-ink-muted mt-1 mb-3 leading-relaxed">{def.description}</p>
            <p className="text-[10px] text-ink-faint mb-3">{def.step_count} steps</p>
            <button
              onClick={() => handleStart(def.template_key)}
              disabled={!!busy}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-accent-devcollab/15 text-accent-devcollab border border-accent-devcollab/30 hover:bg-accent-devcollab/25 disabled:opacity-50"
            >
              {busy === def.template_key ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
              Start Workflow
            </button>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <h3 className="text-sm font-semibold text-ink-primary mb-3">Recent Runs</h3>
          {runs.length === 0 && (
            <p className="text-xs text-ink-muted">No workflow runs yet — start one above.</p>
          )}
          <div className="space-y-2">
            {runs.map((run) => (
              <div
                key={run.id}
                className={`border rounded-lg px-3 py-2 cursor-pointer transition-colors ${
                  selectedRunId === run.id ? "border-accent-devcollab bg-accent-devcollab/5" : "border-base-border bg-base-bg"
                }`}
                onClick={() => loadTimeline(run.id)}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-ink-primary">#{run.id} — {run.name || run.template_key}</span>
                  <span className={`uppercase text-[10px] ${statusColor[run.status] || "text-ink-muted"}`}>
                    {run.status.replace(/_/g, " ")}
                  </span>
                </div>
                <p className="text-[11px] text-ink-faint mt-1">
                  Step {run.current_step_index + 1} · {new Date(run.started_at).toLocaleString()}
                </p>
                <div className="flex gap-2 mt-2">
                  {run.status === "waiting_hitl" && (
                    <button
                      onClick={(e) => { e.stopPropagation(); handleResume(run.id); }}
                      disabled={!!busy}
                      className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-accent-success/15 text-accent-success"
                    >
                      {busy === `resume-${run.id}` ? <Loader2 size={10} className="animate-spin" /> : <CheckCircle size={10} />}
                      Approve & Resume
                    </button>
                  )}
                  {!["completed", "cancelled"].includes(run.status) && (
                    <button
                      onClick={(e) => { e.stopPropagation(); handleCancel(run.id); }}
                      disabled={!!busy}
                      className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-base-border/50 text-ink-muted"
                    >
                      <XCircle size={10} /> Cancel
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <h3 className="text-sm font-semibold text-ink-primary mb-3">Step Timeline</h3>
          {!selectedRunId && (
            <p className="text-xs text-ink-muted">Select a run to view its step-by-step timeline.</p>
          )}
          <div className="space-y-2">
            {timeline.map((step) => (
              <div key={step.id} className="flex items-start gap-3 border-l-2 border-base-border pl-3 py-1">
                <div className="mt-0.5">
                  {step.status === "completed" && <CheckCircle size={12} className="text-accent-success" />}
                  {step.status === "waiting_hitl" && <Clock size={12} className="text-accent-warning" />}
                  {step.status === "failed" && <XCircle size={12} className="text-red-400" />}
                  {step.status === "running" && <Loader2 size={12} className="animate-spin text-accent-devcollab" />}
                </div>
                <div>
                  <p className="text-xs text-ink-primary font-medium">{step.step_id.replace(/_/g, " ")}</p>
                  <p className="text-[11px] text-ink-muted">{step.agent_name}</p>
                  <p className="text-[10px] text-ink-faint uppercase">{step.status}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
