import { apiClient } from './client'
import type { Reservation, ReservationStatus } from './types'

export async function listReservations(
  restaurantId: string,
  status?: ReservationStatus,
  limit = 50,
  offset = 0,
): Promise<Reservation[]> {
  const { data } = await apiClient.get<Reservation[]>(`/restaurants/${restaurantId}/reservations`, {
    params: { status, limit, offset },
  })
  return data
}

export async function updateReservationStatus(
  restaurantId: string,
  reservationId: string,
  status: ReservationStatus,
): Promise<Reservation> {
  const { data } = await apiClient.patch<Reservation>(
    `/restaurants/${restaurantId}/reservations/${reservationId}`,
    { status },
  )
  return data
}
