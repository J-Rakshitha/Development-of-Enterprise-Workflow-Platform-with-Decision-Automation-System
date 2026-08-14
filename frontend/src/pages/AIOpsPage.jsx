import React, { useCallback, useEffect, useState } from "react";
import { ServerCog, RefreshCw, Loader2, GitCommit, ExternalLink, Activity, Radio } from "lucide-react";
import { listIncidents, ingestMetrics, observabilityStatus } from "../services/apiClient";
import { useLiveSocketContext } from "../context/LiveSocketContext";
import { useAuth } from "../context/AuthContext";
import ToolIntegrationPanel from "../components/common/ToolIntegrationPanel";
import SlaCountdown from "../components/common/SlaCountdown";
import { formatLiveDateTime } from "../utils/datetime";

const severityColor = {
  P1: "text-red-400 border-red-500/40",
  P2: "text-accent-warning border-accent-warning/40",
  P3: "text-ink-muted border-base-border",
};

const sourceLabel = {
  webhook: "WEBHOOK",
  monitoring: "MONITORING",
  ingest: "INGEST",
};

/** Incident-generating services for live test ingest — not the same as health-probe targets. */
const INCIDENT_SERVICE_POOL = [
  "checkout-service",
  "payment-service",
  "auth-service",
  "inventory-service",
  "notification-service",
  "order-service",
];

let _lastTestService = null;

function randInt(min, max) {
  const range = max - min + 1;
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    const buf = new Uint32Array(1);
    crypto.getRandomValues(buf);
    return min + (buf[0] % range);
  }
  return Math.floor(Math.random() * range) + min;
}

function pickIncidentService() {
  let pool = INCIDENT_SERVICE_POOL;
  if (_lastTestService && pool.length > 1) {
    pool = pool.filter((s) => s !== _lastTestService);
  }
  const pick = pool[randInt(0, pool.length - 1)];
  _lastTestService = pick;
  return pick;
}

function buildLiveTestMetrics() {
  // Fresh service + metrics each click (crypto-backed random when available)
  return {
    service_name: pickIncidentService(),
    response_time_ms: randInt(2000, 10000),
    error_rate_pct: randInt(40, 95),
    db_pool_usage_pct: randInt(60, 98),
    affected_users_pct: randInt(40, 95),
  };
}

export default function AIOpsPage() {
  const [incidents, setIncidents] = useState([]);
  const [error, setError] = useState(false);
  const [observability, setObservability] = useState(null);
  const [ingesting, setIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState(null);
  const { lastEvent } = useLiveSocketContext();
  const { user } = useAuth();

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
    observabilityStatus().then((res) => setObservability(res.data)).catch(() => {});
  }, [loadIncidents]);

  useEffect(() => {
    if (lastEvent?.type === "incident_created") loadIncidents();
  }, [lastEvent, loadIncidents]);

  async function handleIngestTest() {
    setIngesting(true);
    setIngestResult(null);
    try {
      const res = await ingestMetrics(buildLiveTestMetrics());
      setIngestResult(res.data);
      loadIncidents();
    } catch (err) {
      setIngestResult({
        anomaly_detected: false,
        error: err.response?.data?.detail || err.message,
      });
    } finally {
      setIngesting(false);
    }
  }

  return (
    <div className="space-y-4 p-6">
      {/* Real Observability Integration */}
      <div className="bg-base-surface border border-base-border rounded-xl p-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-ink-primary flex items-center gap-2">
            <Activity size={16} className="text-accent-aiops" />
            Real Observability Integration
          </h2>
          <button
            onClick={handleIngestTest}
            disabled={ingesting}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-accent-aiops/15 text-accent-aiops border border-accent-aiops/30 hover:bg-accent-aiops/25 transition-colors disabled:opacity-50"
          >
            {ingesting ? <Loader2 size={13} className="animate-spin" /> : <Radio size={13} />}
            Send Real Test Metrics
          </button>
        </div>

        <p className="text-xs text-ink-faint mb-2">
          Signed in as <span className="text-ink-primary font-medium">{user?.full_name}</span>.
          Connect Grafana/Prometheus or enable background monitoring for live incidents.
        </p>

        {observability && (
          <div className="text-xs text-ink-faint space-y-1 mb-2">
            <p>
              Monitoring:{" "}
              <span className={observability.monitoring_enabled ? "text-accent-success" : "text-ink-muted"}>
                {observability.monitoring_enabled ? "ON" : "OFF"}
              </span>
              {observability.monitoring_enabled && (
                <span className="text-ink-muted"> — probe every {observability.monitor_interval_seconds}s</span>
              )}
            </p>
            <p title="Health-check probe targets (e.g. coordination-engine-backend). Separate from incident test services used by Send Real Test Metrics.">
              Registered services:{" "}
              <span className="font-mono text-ink-secondary">{observability.registered_services}</span>
              <span className="text-ink-muted"> — health-check targets (not incident test services)</span>
            </p>
            {observability.webhook_url && (
              <p>
                Alert webhook URL:{" "}
                <span className="font-mono text-ink-secondary break-all">{observability.webhook_url}</span>
                {observability.webhook_secret_configured ? (
                  <span className="text-accent-success ml-1">(secret configured)</span>
                ) : (
                  <span className="text-ink-muted ml-1">(set METRICS_WEBHOOK_SECRET in .env for production)</span>
                )}
              </p>
            )}
          </div>
        )}

        {ingestResult && (
          <div
            className={`text-xs rounded-lg px-3 py-2 mt-2 ${
              ingestResult.anomaly_detected
                ? "bg-accent-success/10 text-accent-success"
                : "bg-accent-warning/10 text-accent-warning"
            }`}
          >
            {ingestResult.anomaly_detected
              ? `Incident #${ingestResult.incident_id} created (${ingestResult.severity}) — source: ingest, triggered by ${user?.full_name}`
              : ingestResult.error || "No anomaly detected — metrics below threshold."}
          </div>
        )}
      </div>

      <div className="bg-base-surface border border-base-border rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-ink-primary flex items-center gap-2">
            <ServerCog size={16} className="text-accent-aiops" />
            Live Incident Feed
          </h2>
          <button
            onClick={loadIncidents}
            className="p-1.5 rounded-lg border border-base-border text-ink-muted hover:text-ink-primary transition-colors"
            title="Refresh"
          >
            <RefreshCw size={14} />
          </button>
        </div>

        {error && (
          <p className="text-xs text-ink-muted">
            Backend not reachable — make sure the FastAPI server is running on port 8000.
          </p>
        )}

        {!error && incidents.length === 0 && (
          <p className="text-xs text-ink-muted">
            No incidents yet — connect Grafana webhook, enable monitoring, or click Send Real Test Metrics above.
          </p>
        )}

        <div className="space-y-2">
          {incidents.map((inc) => (
            <div key={inc.id} className={`border rounded-lg px-3 py-2 ${severityColor[inc.severity] || "border-base-border"}`}>
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold">{inc.title}</span>
                <div className="flex items-center gap-1.5">
                  {inc.source && inc.source !== "legacy" && inc.source !== "simulate" && (
                    <span className="uppercase tracking-wide text-[10px] px-2 py-0.5 rounded-full bg-accent-aiops/15 text-accent-aiops">
                      {sourceLabel[inc.source] || String(inc.source).toUpperCase()}
                    </span>
                  )}
                  <span className="uppercase tracking-wide text-[10px]">{inc.severity} · {inc.status}</span>
                </div>
              </div>
              {inc.triggered_by && (
                <p className="text-[10px] text-ink-faint mt-0.5">
                  Triggered by: <span className="text-ink-primary font-medium">{inc.triggered_by}</span>
                  {inc.detected_at ? ` · ${formatLiveDateTime(inc.detected_at)}` : ""}
                  {inc.id != null ? ` · #${inc.id}` : ""}
                </p>
              )}
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
