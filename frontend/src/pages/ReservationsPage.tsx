import { useEffect, useState } from 'react'
import { extractErrorMessage } from '@/api/client'
import { listReservations, updateReservationStatus } from '@/api/reservations'
import type { Reservation, ReservationStatus } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { EmptyState, ErrorBanner, LoadingState, PageHeader } from '@/components/Feedback'
import { formatDate, statusBadgeClasses } from '@/lib/format'

const STATUS_FILTERS: { value: ReservationStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'declined', label: 'Declined' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'completed', label: 'Completed' },
  { value: 'no_show', label: 'No-show' },
]

export function ReservationsPage() {
  const { user } = useAuth()
  const restaurantId = user?.restaurant_id ?? ''
  const [reservations, setReservations] = useState<Reservation[] | null>(null)
  const [filter, setFilter] = useState<ReservationStatus | 'all'>('pending')
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  function load() {
    if (!restaurantId) return
    listReservations(restaurantId, filter === 'all' ? undefined : filter)
      .then(setReservations)
      .catch((err) => setError(extractErrorMessage(err)))
  }

  useEffect(load, [restaurantId, filter])

  async function handleStatusChange(reservationId: string, status: ReservationStatus) {
    setBusyId(reservationId)
    try {
      await updateReservationStatus(restaurantId, reservationId, status)
      load()
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title="Reservation Requests"
        description="Every reservation created by this system is a request, not a confirmed booking — review and confirm or decline each one."
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {STATUS_FILTERS.map((option) => (
          <button
            key={option.value}
            onClick={() => setFilter(option.value)}
            className={`rounded-full px-3 py-1 text-sm font-medium ${
              filter === option.value
                ? 'bg-indigo-600 text-white'
                : 'bg-white text-gray-600 ring-1 ring-gray-300 hover:bg-gray-50'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      {error && <ErrorBanner message={error} />}

      {reservations === null ? (
        <LoadingState />
      ) : reservations.length === 0 ? (
        <EmptyState message="No reservation requests in this view." />
      ) : (
        <ul className="space-y-3">
          {reservations.map((reservation) => (
            <li key={reservation.id} className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-gray-900">
                    {reservation.customer_name} · party of {reservation.party_size}
                  </p>
                  <p className="text-sm text-gray-600">
                    {formatDate(reservation.reservation_date)} at {reservation.reservation_time}
                  </p>
                  <p className="text-sm text-gray-500">{reservation.customer_phone}</p>
                  {reservation.special_notes && (
                    <p className="mt-1 text-sm italic text-gray-500">"{reservation.special_notes}"</p>
                  )}
                  <span
                    className={`mt-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium ${statusBadgeClasses(reservation.status)}`}
                  >
                    {reservation.status.replace('_', ' ')}
                  </span>
                </div>
                {reservation.status === 'pending' && (
                  <div className="flex flex-shrink-0 gap-2">
                    <button
                      onClick={() => handleStatusChange(reservation.id, 'confirmed')}
                      disabled={busyId === reservation.id}
                      className="rounded-lg bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => handleStatusChange(reservation.id, 'declined')}
                      disabled={busyId === reservation.id}
                      className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                    >
                      Decline
                    </button>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
