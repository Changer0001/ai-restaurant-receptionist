import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listCalls } from '@/api/calls'
import { extractErrorMessage } from '@/api/client'
import { listReservations } from '@/api/reservations'
import type { Call, Reservation } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { EmptyState, ErrorBanner, LoadingState, PageHeader } from '@/components/Feedback'
import { formatDateTime, outcomeLabel } from '@/lib/format'

export function DashboardPage() {
  const { user } = useAuth()
  const restaurantId = user?.restaurant_id ?? ''
  const [recentCalls, setRecentCalls] = useState<Call[] | null>(null)
  const [pendingReservations, setPendingReservations] = useState<Reservation[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!restaurantId) return
    let cancelled = false
    Promise.all([listCalls(restaurantId, 5, 0), listReservations(restaurantId, 'pending', 5, 0)])
      .then(([calls, reservations]) => {
        if (cancelled) return
        setRecentCalls(calls)
        setPendingReservations(reservations)
      })
      .catch((err) => {
        if (!cancelled) setError(extractErrorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [restaurantId])

  return (
    <div>
      <PageHeader title="Dashboard" description="Recent activity for your restaurant." />

      {error && <ErrorBanner message={error} />}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <section className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-semibold text-gray-900">Recent Calls</h3>
            <Link to="/calls" className="text-sm text-indigo-600 hover:text-indigo-500">
              View all
            </Link>
          </div>
          {recentCalls === null ? (
            <LoadingState />
          ) : recentCalls.length === 0 ? (
            <EmptyState message="No calls yet." />
          ) : (
            <ul className="divide-y divide-gray-100">
              {recentCalls.map((call) => (
                <li key={call.id} className="py-2">
                  <Link to={`/calls/${call.id}`} className="block hover:text-indigo-600">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{call.caller_number}</span>
                      <span className="text-gray-500">{formatDateTime(call.start_time)}</span>
                    </div>
                    <span className="text-xs text-gray-500">{outcomeLabel(call.outcome)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-semibold text-gray-900">Pending Reservation Requests</h3>
            <Link to="/reservations" className="text-sm text-indigo-600 hover:text-indigo-500">
              View all
            </Link>
          </div>
          {pendingReservations === null ? (
            <LoadingState />
          ) : pendingReservations.length === 0 ? (
            <EmptyState message="No pending requests." />
          ) : (
            <ul className="divide-y divide-gray-100">
              {pendingReservations.map((reservation) => (
                <li key={reservation.id} className="py-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{reservation.customer_name}</span>
                    <span className="text-gray-500">
                      Party of {reservation.party_size}, {reservation.reservation_time}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
