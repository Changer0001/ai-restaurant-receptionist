import { apiClient } from './client'
import type { Restaurant, RestaurantUpdatePayload } from './types'

export async function getRestaurant(restaurantId: string): Promise<Restaurant> {
  const { data } = await apiClient.get<Restaurant>(`/restaurants/${restaurantId}`)
  return data
}

export async function updateRestaurant(
  restaurantId: string,
  payload: RestaurantUpdatePayload,
): Promise<Restaurant> {
  const { data } = await apiClient.patch<Restaurant>(`/restaurants/${restaurantId}`, payload)
  return data
}
