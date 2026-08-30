import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getCall } from '@/api/calls'
import { extractErrorMessage } from '@/api/client'
import type { CallDetail } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { ErrorBanner, LoadingState, PageHeader } from '@/components/Feedback'
import { formatDateTime, formatDuration, outcomeBadgeClasses, outcomeLabel } from '@/lib/format'

export function CallDetailPage() {
  const { callId } = useParams<{ callId: string }>()
  const { user } = useAuth()
  const restaurantId = user?.restaurant_id ?? ''
  const [call, setCall] = useState<CallDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!restaurantId || !callId) return
    getCall(restaurantId, callId)
      .then(setCall)
      .catch((err) => setError(extractErrorMessage(err)))
  }, [restaurantId, callId])

  if (error) return <ErrorBanner message={error} />
  if (!call) return <LoadingState />

  return (
    <div>
      <Link to="/calls" className="text-sm text-indigo-600 hover:text-indigo-500">
        ← Back to calls
      </Link>

      <PageHeader title={`Call from ${call.caller_number}`} />

      <div className="mb-6 grid max-w-2xl grid-cols-2 gap-4 rounded-xl border border-gray-200 bg-white p-5 text-sm sm:grid-cols-4">
        <div>
          <p className="text-gray-500">Started</p>
          <p className="font-medium text-gray-900">{formatDateTime(call.start_time)}</p>
        </div>
        <div>
          <p className="text-gray-500">Duration</p>
          <p className="font-medium text-gray-900">{formatDuration(call.duration_seconds)}</p>
        </div>
        <div>
          <p className="text-gray-500">Outcome</p>
          <span
            className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${outcomeBadgeClasses(call.outcome)}`}
          >
            {outcomeLabel(call.outcome)}
          </span>
        </div>
        <div>
          <p className="text-gray-500">Transferred</p>
          <p className="font-medium text-gray-900">{call.was_transferred ? 'Yes' : 'No'}</p>
        </div>
      </div>

      <h3 className="mb-3 font-semibold text-gray-900">Transcript</h3>
      {call.transcripts.length === 0 ? (
        <p className="text-sm text-gray-500">No transcript recorded for this call.</p>
      ) : (
        <ol className="max-w-2xl space-y-3">
          {call.transcripts.map((turn, index) => (
            <li
              key={index}
              className={`rounded-xl border p-3 text-sm ${
                turn.role === 'assistant'
                  ? 'border-indigo-100 bg-indigo-50'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
                {turn.role}
              </p>
              <p className="text-gray-800">{turn.message}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
