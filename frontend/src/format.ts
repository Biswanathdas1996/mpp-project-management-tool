import type { Health, Status } from '@/api/types'
import { i18n } from '@/i18n'

const loc = () => (i18n.global.locale.value === 'ar' ? 'ar' : 'en-GB')

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${Number(v).toFixed(digits)}%`
}
export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return Number(v).toLocaleString(loc(), { maximumFractionDigits: digits, minimumFractionDigits: digits })
}
export function int(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : String(Math.round(v))
}
export function pts(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(1)} pts`
}
export function date(d: string | null | undefined, style: 'short' | 'medium' = 'medium'): string {
  if (!d) return '—'
  const dt = new Date(d.length === 10 ? `${d}T00:00:00` : d)
  if (Number.isNaN(dt.getTime())) return d
  return dt.toLocaleDateString(loc(), style === 'short' ? { day: '2-digit', month: 'short' } : { day: '2-digit', month: 'short', year: 'numeric' })
}
export function datetime(d: string | null | undefined): string {
  if (!d) return '—'
  return new Date(d).toLocaleString(loc(), { dateStyle: 'medium', timeStyle: 'short' })
}
export function monthYear(d: string | null | undefined): string {
  if (!d) return '—'
  return new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString(loc(), { month: 'long', year: 'numeric' })
}
export function two(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : String(n).padStart(2, '0')
}
export function bytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export const STATUS_CLASS: Record<Status, string> = {
  completed: 'info', on_track: 'ok', delay: 'warn', critical_delay: 'bad', not_started: 'neutral',
}
export const STATUS_COLOR_VAR: Record<Status, string> = {
  completed: 'var(--c-completed)', on_track: 'var(--c-on-track)', delay: 'var(--c-delay)',
  critical_delay: 'var(--c-critical)', not_started: 'var(--c-not-started)',
}
export function statusClass(s: string | null | undefined): string {
  return STATUS_CLASS[(s || 'not_started') as Status] || 'neutral'
}
export function healthClass(h: Health | null | undefined): string {
  if (!h) return 'neutral'
  return { done: 'info', low: 'neutral', medium: 'warn', high: 'bad', critical: 'bad' }[h.urgency] || 'neutral'
}
export function severityClass(s: string): string {
  return { Critical: 'bad', High: 'bad', Medium: 'warn', Low: 'neutral' }[s] || 'neutral'
}
export function priorityClass(s: string): string {
  return { High: 'bad', Medium: 'warn', Low: 'neutral' }[s] || 'neutral'
}
export function decisionStatusClass(s: string): string {
  return { Pending: 'warn', Approved: 'ok', Rejected: 'bad' }[s] || 'neutral'
}
export function varianceClass(v: number | null | undefined): string {
  if (v === null || v === undefined || Math.abs(v) < 0.05) return 'neutral'
  return v > 0 ? 'ok' : 'bad'
}
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
