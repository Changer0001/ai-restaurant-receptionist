import { apiClient } from './client'
import type { FAQ, FAQCreatePayload, FAQUpdatePayload } from './types'

export async function listFaqs(restaurantId: string): Promise<FAQ[]> {
  const { data } = await apiClient.get<FAQ[]>(`/restaurants/${restaurantId}/faqs`)
  return data
}

export async function createFaq(restaurantId: string, payload: FAQCreatePayload): Promise<FAQ> {
  const { data } = await apiClient.post<FAQ>(`/restaurants/${restaurantId}/faqs`, payload)
  return data
}

export async function updateFaq(
  restaurantId: string,
  faqId: string,
  payload: FAQUpdatePayload,
): Promise<FAQ> {
  const { data } = await apiClient.patch<FAQ>(`/restaurants/${restaurantId}/faqs/${faqId}`, payload)
  return data
}

export async function deleteFaq(restaurantId: string, faqId: string): Promise<void> {
  await apiClient.delete(`/restaurants/${restaurantId}/faqs/${faqId}`)
}
