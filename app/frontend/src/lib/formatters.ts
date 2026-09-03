export function formatMoney(paise: number, currency = "INR") { try { return new Intl.NumberFormat("en-IN", { style: "currency", currency, minimumFractionDigits: 2 }).format(paise / 100); } catch { return `${currency} ${(paise / 100).toFixed(2)}`; } }
export function formatDate(value?: string | null) { if (!value) return "—"; const date = new Date(value); return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(date); }
export function formatScore(value?: number | null) { return value == null ? "Not scored" : `${Math.round(value * 100)}%`; }
export function humanize(value?: string | null) { return value ? value.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : "—"; }
export function shortId(value: string) { return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value; }
