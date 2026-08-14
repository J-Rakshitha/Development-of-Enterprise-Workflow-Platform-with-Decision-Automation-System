import React, { useEffect, useState } from "react";
import { Clock, AlertTriangle, CheckCircle2 } from "lucide-react";
import { formatLiveDateTime, parseUtcDate } from "../../utils/datetime";

/** Generic labels that look like demo/fake teams — hide from AIOps cards. */
const HIDDEN_ESCALATION_LABELS = new Set([
  "backend engineering team",
  "incident response",
  "sla watchdog",
  "on call",
  "on-call",
  "oncall",
]);

function visibleEscalationTarget(escalatedTo) {
  if (!escalatedTo || typeof escalatedTo !== "string") return null;
  const label = escalatedTo.trim().toLowerCase();
  if (HIDDEN_ESCALATION_LABELS.has(label)) return null;
  return escalatedTo.trim();
}

function formatDuration(totalSeconds) {
  const abs = Math.abs(totalSeconds);
  const h = Math.floor(abs / 3600);
  const m = Math.floor((abs % 3600) / 60);
  const s = abs % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export default function SlaCountdown({ slaDeadline, slaMinutes, status, resolvedAt, detectedAt, escalatedTo }) {
  const [now, setNow] = useState(() => Date.now());
  const deadline = parseUtcDate(slaDeadline);
  const deadlineMs = deadline ? deadline.getTime() : null;
  const remainingSec = deadlineMs ? Math.floor((deadlineMs - now) / 1000) : null;
  const isResolved = status === "auto_resolved" || status === "closed";
  const isEscalated = status === "escalated" || Boolean(escalatedTo);
  const breached = remainingSec != null && remainingSec <= 0;
  const escalationTarget = visibleEscalationTarget(escalatedTo);

  useEffect(() => {
    if (isResolved || breached) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [isResolved, breached]);

  if (!slaDeadline && !slaMinutes) return null;

  if (isResolved && resolvedAt && deadlineMs) {
    const resolved = parseUtcDate(resolvedAt);
    const detected = parseUtcDate(detectedAt);
    const resolvedMs = resolved ? resolved.getTime() : NaN;
    const detectedMs = detected ? detected.getTime() : NaN;
    const metSla = resolvedMs <= deadlineMs;
    return (
      <div
        className={`flex items-center gap-1.5 mt-2 text-[11px] rounded-md px-2 py-1 ${
          metSla ? "text-accent-success bg-accent-success/10" : "text-accent-warning bg-accent-warning/10"
        }`}
      >
        {metSla ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
        <span>
          {metSla ? "SLA met" : "SLA missed"} — resolved in{" "}
          {formatDuration(Math.floor((resolvedMs - detectedMs) / 1000))}
          {slaMinutes ? ` (target: ${slaMinutes} min)` : ""}
        </span>
      </div>
    );
  }

  if (remainingSec == null) return null;

  if (breached) {
    return (
      <div className="mt-2 space-y-1">
        <div className="flex items-center gap-1.5 text-[11px] rounded-md px-2 py-1 text-red-400 bg-red-500/10 border border-red-500/30">
          <AlertTriangle size={12} />
          <span>
            SLA missed at {formatLiveDateTime(slaDeadline)}
            {slaMinutes ? ` (${slaMinutes} min SLA)` : ""}
          </span>
        </div>
        {escalationTarget && (
          <p className="text-[10px] text-ink-muted px-2">Escalated to: {escalationTarget}</p>
        )}
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-1">
      <div
        className={`flex items-center gap-1.5 text-[11px] rounded-md px-2 py-1 ${
          isEscalated
            ? "text-accent-warning bg-accent-warning/10"
            : "text-accent-aiops bg-accent-aiops/10"
        }`}
      >
        <Clock size={12} />
        <span>
          SLA countdown: {formatDuration(remainingSec)} remaining
          {slaMinutes ? ` (${slaMinutes} min SLA)` : ""}
        </span>
      </div>
      {escalationTarget && (
        <p className="text-[10px] text-ink-muted px-2">Escalated to: {escalationTarget}</p>
      )}
    </div>
  );
}
