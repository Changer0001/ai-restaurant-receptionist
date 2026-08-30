import type { CallOutcome, ReservationStatus } from '@/api/types'

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' })
}

const OUTCOME_LABELS: Record<CallOutcome, string> = {
  faq_answered: 'FAQ answered',
  reservation_created: 'Reservation created',
  call_transferred: 'Transferred',
  human_escalation: 'Escalated to human',
  call_abandoned: 'Abandoned',
  unknown: 'Unknown',
}

export function outcomeLabel(outcome: CallOutcome): string {
  return OUTCOME_LABELS[outcome] ?? outcome
}

const OUTCOME_BADGE_CLASSES: Record<CallOutcome, string> = {
  faq_answered: 'bg-blue-100 text-blue-800',
  reservation_created: 'bg-green-100 text-green-800',
  call_transferred: 'bg-purple-100 text-purple-800',
  human_escalation: 'bg-amber-100 text-amber-800',
  call_abandoned: 'bg-gray-100 text-gray-700',
  unknown: 'bg-gray-100 text-gray-700',
}

export function outcomeBadgeClasses(outcome: CallOutcome): string {
  return OUTCOME_BADGE_CLASSES[outcome] ?? 'bg-gray-100 text-gray-700'
}

const STATUS_BADGE_CLASSES: Record<ReservationStatus, string> = {
  pending: 'bg-amber-100 text-amber-800',
  confirmed: 'bg-green-100 text-green-800',
  declined: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-700',
  completed: 'bg-blue-100 text-blue-800',
  no_show: 'bg-red-100 text-red-800',
}

export function statusBadgeClasses(status: ReservationStatus): string {
  return STATUS_BADGE_CLASSES[status] ?? 'bg-gray-100 text-gray-700'
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return `${minutes}m ${remainder}s`
}

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export function dayName(dayOfWeek: number): string {
  return DAY_NAMES[dayOfWeek] ?? `Day ${dayOfWeek}`
}
