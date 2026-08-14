import React, { useCallback, useEffect, useState } from "react";
import { GitBranch, ServerCog, Activity, Link2 } from "lucide-react";
import StatCard from "../components/common/StatCard";
import NotificationsPanel from "../components/common/NotificationsPanel";
import { getStats } from "../services/apiClient";
import { useLiveSocketContext } from "../context/LiveSocketContext";
import { useAuth } from "../context/AuthContext";

export default function OverviewPage() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(false);
  const { lastEvent } = useLiveSocketContext();
  const { user } = useAuth();

  const loadStats = useCallback(() => {
    getStats()
      .then((res) => {
        setStats(res.data);
        setError(false);
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);
  useEffect(() => { if (lastEvent) loadStats(); }, [lastEvent, loadStats]);

  const val = (n) => (error || stats === null ? "—" : n);

  return (
    <div className="p-6 space-y-4 max-w-6xl mx-auto">
      <div className="bg-base-surface border border-base-border rounded-xl p-4">
        <p className="text-sm text-ink-primary">
          Welcome, <span className="font-semibold text-accent-devcollab">{user?.full_name}</span>
          <span className="text-ink-muted"> — enterprise workflow dashboard</span>
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Active Edit Sessions" value={val(stats?.active_edit_sessions)} accent="devcollab" icon={GitBranch} />
        <StatCard label="Conflicts Predicted" value={val(stats?.conflicts_predicted)} accent="warning" icon={Activity} />
        <StatCard label="Open Incidents" value={val(stats?.open_incidents)} accent="aiops" icon={ServerCog} />
        <StatCard label="Linked Incidents" value={val(stats?.linked_incidents)} accent="success" icon={Link2} />
      </div>

      <div className="bg-base-surface border border-base-border rounded-xl p-6">
        <h2 className="font-display text-base font-semibold text-ink-primary mb-2">
          Software Development Lifecycle — Unified Coordination
        </h2>
        <p className="text-sm text-ink-muted leading-relaxed">
          Dev-Collaboration prevents merge conflicts. AIOps handles production incidents.
          Coordinator links both modules. All actions are tracked per signed-in user with human approval.
        </p>
        {error && (
          <p className="text-xs text-ink-faint mt-4">
            Backend not reachable — start the FastAPI server to see live counts here.
          </p>
        )}
      </div>

      <NotificationsPanel />
    </div>
  );
}
