/** Parse backend UTC timestamps (naive ISO or with Z) into a Date. */
export function parseUtcDate(iso) {
  if (!iso) return null;
  const raw = String(iso);
  const normalized =
    /Z$|[+-]\d{2}:\d{2}$/.test(raw) ? raw : raw.includes("T") ? `${raw}Z` : raw;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatLiveTime(iso) {
  const d = parseUtcDate(iso);
  if (!d) return iso ? String(iso) : "";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

export function formatLiveDateTime(iso) {
  const d = parseUtcDate(iso);
  if (!d) return iso ? String(iso) : "";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}
