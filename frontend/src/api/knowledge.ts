import { apiClient } from './client'
import type { KnowledgeDocument } from './types'

export async function listKnowledgeDocuments(restaurantId: string): Promise<KnowledgeDocument[]> {
  const { data } = await apiClient.get<KnowledgeDocument[]>(`/restaurants/${restaurantId}/knowledge`)
  return data
}

export async function uploadKnowledgeDocument(
  restaurantId: string,
  file: File,
  title: string,
  documentType: string,
): Promise<KnowledgeDocument> {
  const form = new FormData()
  form.append('file', file)
  form.append('title', title)
  form.append('document_type', documentType)
  const { data } = await apiClient.post<KnowledgeDocument>(
    `/restaurants/${restaurantId}/knowledge/upload`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

export async function deleteKnowledgeDocument(restaurantId: string, documentId: string): Promise<void> {
  await apiClient.delete(`/restaurants/${restaurantId}/knowledge/${documentId}`)
}

export async function reindexKnowledgeDocument(
  restaurantId: string,
  documentId: string,
): Promise<KnowledgeDocument> {
  const { data } = await apiClient.post<KnowledgeDocument>(
    `/restaurants/${restaurantId}/knowledge/${documentId}/reindex`,
  )
  return data
}
