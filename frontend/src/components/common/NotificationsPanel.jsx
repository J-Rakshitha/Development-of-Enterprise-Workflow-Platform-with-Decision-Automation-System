import React, { useCallback, useEffect, useState } from "react";
import { Bell, Mail, Radio, Check } from "lucide-react";
import { getNotifications, acknowledgeNotification } from "../../services/apiClient";
import { useLiveSocketContext } from "../../context/LiveSocketContext";
import { formatLiveDateTime } from "../../utils/datetime";

const eventLabel = {
  conflict_detected: "Conflict Detected",
  conflict_resolved: "Conflict Resolved",
  incident_created: "Incident Created",
};

const moduleAccent = {
  dev_collab: "text-accent-devcollab",
  aiops: "text-accent-aiops",
};

function channelIcon(channel) {
  if (channel === "websocket") return Radio;
  if (channel === "slack" || channel === "slack_failed") return Bell;
  if (channel === "discord" || channel === "discord_failed") return Bell;
  if (channel === "teams" || channel === "teams_failed") return Bell;
  return Mail;
}

function channelLabel(channel) {
  if (channel === "websocket") return "Live";
  if (channel === "email") return "Email";
  if (channel === "email_simulated") return "Email (simulated)";
  if (channel === "email_failed") return "Email (failed)";
  if (channel === "slack") return "Slack";
  if (channel === "slack_failed") return "Slack (failed)";
  if (channel === "discord") return "Discord";
  if (channel === "discord_failed") return "Discord (failed)";
  if (channel === "teams") return "Teams";
  if (channel === "teams_failed") return "Teams (failed)";
  return channel;
}

function formatRecipient(recipient) {
  if (!recipient) return "";
  let name = recipient;
  if (name.startsWith("ops:")) name = name.slice(4);
  else if (name.startsWith("github:")) name = name.slice(7);
  if (/^on[-\s]?call$/i.test(name.trim())) return "Incident Response";
  return name;
}

export default function NotificationsPanel() {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(false);
  const { lastEvent } = useLiveSocketContext();

  const load = useCallback(() => {
    getNotifications()
      .then((res) => {
        setEntries(res.data);
        setError(false);
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (lastEvent) load();
  }, [lastEvent, load]);

  async function handleAck(id) {
    try {
      await acknowledgeNotification(id);
      load();
    } catch { /* non-fatal */ }
  }

  const visible = entries.filter((n) => n.channel !== "websocket").slice(0, 12);

  return (
    <div className="bg-base-surface border border-base-border rounded-xl p-4">
      <h2 className="text-sm font-semibold text-ink-primary mb-1 flex items-center gap-2">
        <Bell size={16} className="text-accent-warning" />
        Team Notifications
      </h2>
      <p className="text-xs text-ink-faint mb-3">
        Alerts delivered by the Notification Agent — WebSocket live updates plus email delivery
        records (real SMTP when configured, otherwise simulated in DB).
      </p>

      {error && (
        <p className="text-xs text-ink-muted">Backend not reachable — start the FastAPI server.</p>
      )}

      {!error && visible.length === 0 && (
        <p className="text-xs text-ink-muted">
          No alerts yet — sync GitHub for PR conflict alerts, or create a real incident (Send Real Test Metrics / Grafana webhook).
        </p>
      )}

      <div className="space-y-2">
        {visible.map((n) => {
          const Icon = channelIcon(n.channel);
          return (
            <div key={n.id} className="bg-base-bg border border-base-border rounded-lg px-3 py-2">
              <div className="flex items-center justify-between text-[11px] mb-1">
                <span className={`font-medium ${moduleAccent[n.module] || "text-ink-primary"}`}>
                  {eventLabel[n.event_type] || n.event_type}
                </span>
                <span className="flex items-center gap-1 text-ink-faint">
                  <Icon size={10} />
                  {channelLabel(n.channel)}
                </span>
              </div>
              <p className="text-xs text-ink-primary font-medium mb-0.5">{n.subject}</p>
              <p className="text-[11px] text-ink-muted truncate">{formatRecipient(n.recipient)}</p>
              <p className="text-[11px] text-ink-faint mt-1">
                {formatLiveDateTime(n.created_at)}
              </p>
              {!n.acknowledged && (
                <button
                  onClick={() => handleAck(n.id)}
                  className="mt-1.5 flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-accent-success/10 text-accent-success hover:bg-accent-success/20"
                >
                  <Check size={10} /> Acknowledge
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
