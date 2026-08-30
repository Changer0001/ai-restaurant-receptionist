import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listCalls } from '@/api/calls'
import { extractErrorMessage } from '@/api/client'
import type { Call } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { EmptyState, ErrorBanner, LoadingState, PageHeader } from '@/components/Feedback'
import { formatDateTime, formatDuration, outcomeBadgeClasses, outcomeLabel } from '@/lib/format'

export function CallsPage() {
  const { user } = useAuth()
  const restaurantId = user?.restaurant_id ?? ''
  const [calls, setCalls] = useState<Call[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!restaurantId) return
    listCalls(restaurantId)
      .then(setCalls)
      .catch((err) => setError(extractErrorMessage(err)))
  }, [restaurantId])

  return (
    <div>
      <PageHeader title="Call History" description="Every call the AI receptionist has handled." />

      {error && <ErrorBanner message={error} />}

      {calls === null ? (
        <LoadingState />
      ) : calls.length === 0 ? (
        <EmptyState message="No calls yet." />
      ) : (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-4 py-3">Caller</th>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Duration</th>
                <th className="px-4 py-3">Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {calls.map((call) => (
                <tr key={call.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <Link to={`/calls/${call.id}`} className="font-medium text-indigo-600 hover:text-indigo-500">
                      {call.caller_number}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{formatDateTime(call.start_time)}</td>
                  <td className="px-4 py-3 text-gray-600">{formatDuration(call.duration_seconds)}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${outcomeBadgeClasses(call.outcome)}`}
                    >
                      {outcomeLabel(call.outcome)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
