import { apiClient } from './client'
import type { HoursEntry, HoursRead } from './types'

export async function getHours(restaurantId: string): Promise<HoursRead[]> {
  const { data } = await apiClient.get<HoursRead[]>(`/restaurants/${restaurantId}/hours`)
  return data
}

export async function replaceHours(restaurantId: string, hours: HoursEntry[]): Promise<HoursRead[]> {
  const { data } = await apiClient.put<HoursRead[]>(`/restaurants/${restaurantId}/hours`, { hours })
  return data
}
