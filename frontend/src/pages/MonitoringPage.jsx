import React, { useCallback, useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, CartesianGrid,
} from "recharts";
import { Activity, RefreshCw, Server, Gauge, Loader2, CheckCircle, XCircle } from "lucide-react";
import {
  getMonitoringSummary,
  getMonitoringHistory,
  getAgentMetrics,
  getWorkflowStats,
  triggerProbe,
} from "../services/apiClient";
import { useLiveSocketContext } from "../context/LiveSocketContext";
import { useAuth } from "../context/AuthContext";

export default function MonitoringPage() {
  const [summary, setSummary] = useState(null);
  const [history, setHistory] = useState([]);
  const [agentMetrics, setAgentMetrics] = useState(null);
  const [wfStats, setWfStats] = useState(null);
  const [selectedService, setSelectedService] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const { lastEvent } = useLiveSocketContext();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [sumRes, metricsRes, wfRes] = await Promise.all([
        getMonitoringSummary(),
        getAgentMetrics(),
        getWorkflowStats(),
      ]);
      setSummary(sumRes.data);
      setAgentMetrics(metricsRes.data);
      setWfStats(wfRes.data);
      setError(false);
      const services = sumRes.data?.services || [];
      const svc = selectedService || services[0]?.service_name;
      if (svc) {
        setSelectedService(svc);
        const histRes = await getMonitoringHistory(svc, 30);
        setHistory(
          (histRes.data || [])
            .slice()
            .reverse()
            .map((h, i) => ({
              idx: i + 1,
              ms: h.response_time_ms || 0,
              healthy: h.healthy,
              time: new Date(h.checked_at).toLocaleTimeString(),
            }))
        );
      }
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [selectedService]);

  useEffect(() => { loadAll(); }, [loadAll]);
  useEffect(() => {
    if (lastEvent?.type === "service_health_update" || lastEvent?.type === "sla_breach") loadAll();
  }, [lastEvent, loadAll]);

  async function handleProbe() {
    if (!isAdmin) return;
    setLoading(true);
    try {
      await triggerProbe();
      await loadAll();
    } catch { /* non-fatal */ }
    finally { setLoading(false); }
  }

  async function selectService(name) {
    setSelectedService(name);
    try {
      const histRes = await getMonitoringHistory(name, 30);
      setHistory(
        (histRes.data || [])
          .slice()
          .reverse()
          .map((h, i) => ({
            idx: i + 1,
            ms: h.response_time_ms || 0,
            healthy: h.healthy,
            time: new Date(h.checked_at).toLocaleTimeString(),
          }))
      );
    } catch { /* non-fatal */ }
  }

  const services = summary?.services || [];

  return (
    <div className="p-6 space-y-4 max-w-6xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-base font-semibold text-ink-primary flex items-center gap-2">
            <Gauge size={18} className="text-accent-aiops" />
            Operations Monitoring Dashboard
          </h2>
          <p className="text-xs text-ink-muted mt-1">
            Real probe data from background scheduler — response time, uptime, agent performance, workflow stats.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadAll}
            disabled={loading}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-base-border text-ink-muted hover:text-ink-primary"
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            Refresh
          </button>
          {isAdmin && (
            <button
              onClick={handleProbe}
              disabled={loading}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-accent-aiops/15 text-accent-aiops border border-accent-aiops/30"
            >
              <Activity size={13} />
              Trigger Probe
            </button>
          )}
        </div>
      </div>

      {error && (
        <p className="text-xs text-ink-muted">Backend not reachable — start FastAPI on port 8000.</p>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <p className="text-[10px] uppercase tracking-wide text-ink-muted">Monitored Services</p>
          <p className="text-2xl font-semibold text-ink-primary">{services.length || "—"}</p>
        </div>
        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <p className="text-[10px] uppercase tracking-wide text-ink-muted">Agent Decisions</p>
          <p className="text-2xl font-semibold text-ink-primary">{agentMetrics?.total_decisions ?? "—"}</p>
        </div>
        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <p className="text-[10px] uppercase tracking-wide text-ink-muted">Workflow Runs</p>
          <p className="text-2xl font-semibold text-ink-primary">{wfStats?.total_runs ?? "—"}</p>
        </div>
        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <p className="text-[10px] uppercase tracking-wide text-ink-muted">Waiting HITL</p>
          <p className="text-2xl font-semibold text-accent-warning">{wfStats?.waiting_hitl ?? "—"}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <h3 className="text-sm font-semibold text-ink-primary mb-3 flex items-center gap-2">
            <Server size={15} />
            Service Health
          </h3>
          <div className="space-y-2">
            {services.map((s) => (
              <button
                key={s.service_name}
                onClick={() => selectService(s.service_name)}
                className={`w-full text-left border rounded-lg px-3 py-2 transition-colors ${
                  selectedService === s.service_name
                    ? "border-accent-aiops bg-accent-aiops/5"
                    : "border-base-border bg-base-bg hover:border-base-border/80"
                }`}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-ink-primary">{s.service_name}</span>
                  {s.healthy === true ? (
                    <CheckCircle size={14} className="text-accent-success" />
                  ) : s.healthy === false ? (
                    <XCircle size={14} className="text-red-400" />
                  ) : (
                    <span className="text-ink-faint">—</span>
                  )}
                </div>
                <div className="flex justify-between text-[11px] text-ink-muted mt-1">
                  <span>{s.response_time_ms != null ? `${s.response_time_ms}ms` : "No data"}</span>
                  <span>{s.uptime_24h_pct != null ? `${s.uptime_24h_pct}% uptime (24h)` : "—"}</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="bg-base-surface border border-base-border rounded-xl p-4">
          <h3 className="text-sm font-semibold text-ink-primary mb-3">
            Response Time — {selectedService || "select a service"}
          </h3>
          {history.length === 0 ? (
            <p className="text-xs text-ink-muted">No probe history yet. Enable monitoring or trigger a probe.</p>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={history}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" opacity={0.2} />
                <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} unit="ms" />
                <Tooltip contentStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="ms" stroke="#60a5fa" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="bg-base-surface border border-base-border rounded-xl p-4">
        <h3 className="text-sm font-semibold text-ink-primary mb-3">Agent Performance</h3>
        {!agentMetrics?.agents?.length ? (
          <p className="text-xs text-ink-muted">Run workflows or simulate incidents to populate agent metrics.</p>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={agentMetrics.agents.slice(0, 8)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" opacity={0.2} />
              <XAxis dataKey="agent_name" tick={{ fontSize: 9 }} angle={-20} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Bar dataKey="run_count" fill="#34d399" name="Runs" />
              <Bar dataKey="llm_count" fill="#a78bfa" name="LLM" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
