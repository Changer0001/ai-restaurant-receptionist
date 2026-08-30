import { apiClient } from './client'
import type { Call, CallDetail } from './types'

export async function listCalls(restaurantId: string, limit = 50, offset = 0): Promise<Call[]> {
  const { data } = await apiClient.get<Call[]>(`/restaurants/${restaurantId}/calls`, {
    params: { limit, offset },
  })
  return data
}

export async function getCall(restaurantId: string, callId: string): Promise<CallDetail> {
  const { data } = await apiClient.get<CallDetail>(`/restaurants/${restaurantId}/calls/${callId}`)
  return data
}
