import React, { useCallback, useEffect, useState } from "react";
import { ServerCog, RefreshCw, Sparkles, Loader2, GitCommit, ExternalLink } from "lucide-react";
import { listIncidents, simulateIncident } from "../services/apiClient";
import { useLiveSocketContext } from "../context/LiveSocketContext";
import { useAppConfig } from "../context/AppConfigContext";
import ToolIntegrationPanel from "../components/common/ToolIntegrationPanel";
import SlaCountdown from "../components/common/SlaCountdown";

const severityColor = {
  P1: "text-red-400 border-red-500/40",
  P2: "text-accent-warning border-accent-warning/40",
  P3: "text-ink-muted border-base-border",
};

export default function AIOpsPage() {
  const [incidents, setIncidents] = useState([]);
  const [error, setError] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const { lastEvent } = useLiveSocketContext();
  const { simulateEnabled } = useAppConfig();

  const loadIncidents = useCallback(() => {
    listIncidents()
      .then((res) => {
        setIncidents(res.data);
        setError(false);
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    loadIncidents();
  }, [loadIncidents]);

  useEffect(() => {
    if (lastEvent?.type === "incident_created") loadIncidents();
  }, [lastEvent, loadIncidents]);

  async function handleSimulate() {
    setSimulating(true);
    try {
      await simulateIncident();
      loadIncidents();
    } catch {
      setError(true);
    } finally {
      setSimulating(false);
    }
  }

  return (
    <div className="space-y-4 p-6">
      <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-ink-primary flex items-center gap-2">
              <ServerCog size={16} className="text-accent-aiops" />
              Live Incident Feed
            </h2>
            <div className="flex items-center gap-2">
              <button
                onClick={loadIncidents}
                className="p-1.5 rounded-lg border border-base-border text-ink-muted hover:text-ink-primary transition-colors"
                title="Refresh"
              >
                <RefreshCw size={14} />
              </button>
              {simulateEnabled && (
                <button
                  onClick={handleSimulate}
                  disabled={simulating}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-accent-aiops/15 text-accent-aiops border border-accent-aiops/30 hover:bg-accent-aiops/25 transition-colors disabled:opacity-50"
                >
                  {simulating ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                  Simulate Incident
                </button>
              )}
            </div>
          </div>

          {error && (
            <p className="text-xs text-ink-muted">
              Backend not reachable — make sure the FastAPI server is running on port 8000.
            </p>
          )}

          {!error && incidents.length === 0 && (
            <p className="text-xs text-ink-muted">
              No incidents recorded yet.
              {simulateEnabled
                ? <> Click <span className="text-accent-aiops">Simulate Incident</span> to trigger a realistic anomaly.</>
                : <> Background probes or admin <span className="text-accent-aiops">Trigger Probe</span> will populate incidents.</>}
            </p>
          )}

          <div className="space-y-2">
            {incidents.map((inc) => (
              <div key={inc.id} className={`border rounded-lg px-3 py-2 ${severityColor[inc.severity] || "border-base-border"}`}>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold">{inc.title}</span>
                  <span className="uppercase tracking-wide text-[10px]">{inc.severity} · {inc.status}</span>
                </div>
                {inc.root_cause && <p className="text-xs text-ink-muted mt-1">{inc.root_cause}</p>}
                <SlaCountdown
                  slaDeadline={inc.sla_deadline}
                  slaMinutes={inc.sla_minutes}
                  status={inc.status}
                  resolvedAt={inc.resolved_at}
                  detectedAt={inc.detected_at}
                  escalatedTo={inc.escalated_to}
                />
                {inc.mttr_seconds != null && (
                  <p className="text-[10px] text-ink-faint mt-1">Resolved in {inc.mttr_seconds}s</p>
                )}
                {inc.linked_commit && (
                  <div className="flex items-center gap-1.5 mt-2 text-[11px] text-accent-success bg-accent-success/10 rounded-md px-2 py-1">
                    <GitCommit size={12} />
                    <span>
                      Linked to commit <span className="font-mono">{inc.linked_commit.commit_hash}</span> —{" "}
                      {inc.linked_commit.message}
                    </span>
                  </div>
                )}
                {inc.external_references && inc.external_references.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {inc.external_references.map((ref, idx) => (
                      <a
                        key={idx}
                        href={ref.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1.5 text-[11px] text-accent-devcollab bg-accent-devcollab/10 rounded-md px-2 py-1 hover:bg-accent-devcollab/20 transition-colors"
                      >
                        <ExternalLink size={11} />
                        <span className="truncate">GitHub: {ref.title}</span>
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

      <ToolIntegrationPanel />
    </div>
  );
}
