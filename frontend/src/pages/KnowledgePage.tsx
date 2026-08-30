import { useEffect, useRef, useState, type FormEvent } from 'react'
import { extractErrorMessage } from '@/api/client'
import {
  deleteKnowledgeDocument,
  listKnowledgeDocuments,
  reindexKnowledgeDocument,
  uploadKnowledgeDocument,
} from '@/api/knowledge'
import type { KnowledgeDocument } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { EmptyState, ErrorBanner, LoadingState, PageHeader } from '@/components/Feedback'

const DOCUMENT_TYPES = ['general', 'menu', 'policy']

export function KnowledgePage() {
  const { user } = useAuth()
  const restaurantId = user?.restaurant_id ?? ''
  const [documents, setDocuments] = useState<KnowledgeDocument[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [documentType, setDocumentType] = useState(DOCUMENT_TYPES[0])
  const [uploading, setUploading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function load() {
    if (!restaurantId) return
    listKnowledgeDocuments(restaurantId)
      .then(setDocuments)
      .catch((err) => setError(extractErrorMessage(err)))
  }

  useEffect(load, [restaurantId])

  async function handleUpload(event: FormEvent) {
    event.preventDefault()
    const file = fileInputRef.current?.files?.[0]
    if (!file) {
      setUploadError('Choose a .txt or .md file to upload.')
      return
    }
    setUploading(true)
    setUploadError(null)
    try {
      await uploadKnowledgeDocument(restaurantId, file, title || file.name, documentType)
      setTitle('')
      if (fileInputRef.current) fileInputRef.current.value = ''
      load()
    } catch (err) {
      setUploadError(extractErrorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete(documentId: string) {
    setBusyId(documentId)
    try {
      await deleteKnowledgeDocument(restaurantId, documentId)
      load()
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  async function handleReindex(documentId: string) {
    setBusyId(documentId)
    try {
      await reindexKnowledgeDocument(restaurantId, documentId)
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
        title="Knowledge Base"
        description="Plain-text documents (.txt, .md) the AI searches to answer questions it can't answer from FAQs or hours alone."
      />

      <form
        onSubmit={handleUpload}
        className="mb-6 max-w-2xl space-y-3 rounded-xl border border-gray-200 bg-white p-5"
      >
        <h3 className="font-semibold text-gray-900">Upload a document</h3>
        <div>
          <label className="block text-sm font-medium text-gray-700" htmlFor="doc_title">
            Title
          </label>
          <input
            id="doc_title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Defaults to the file name"
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700" htmlFor="doc_type">
            Type
          </label>
          <select
            id="doc_type"
            value={documentType}
            onChange={(e) => setDocumentType(e.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            {DOCUMENT_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700" htmlFor="doc_file">
            File (.txt or .md)
          </label>
          <input
            id="doc_file"
            ref={fileInputRef}
            type="file"
            accept=".txt,.md,text/plain,text/markdown"
            className="mt-1 w-full text-sm"
          />
        </div>

        {uploadError && <ErrorBanner message={uploadError} />}

        <button
          type="submit"
          disabled={uploading}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {uploading ? 'Uploading…' : 'Upload'}
        </button>
      </form>

      {error && <ErrorBanner message={error} />}

      {documents === null ? (
        <LoadingState />
      ) : documents.length === 0 ? (
        <EmptyState message="No knowledge documents yet." />
      ) : (
        <ul className="max-w-2xl space-y-3">
          {documents.map((doc) => (
            <li key={doc.id} className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-gray-900">{doc.title}</p>
                  <p className="text-xs text-gray-500">
                    {doc.document_type} · {doc.chunk_count} chunk{doc.chunk_count === 1 ? '' : 's'}
                  </p>
                </div>
                <div className="flex flex-shrink-0 gap-2">
                  <button
                    onClick={() => handleReindex(doc.id)}
                    disabled={busyId === doc.id}
                    className="text-sm text-indigo-600 hover:text-indigo-500 disabled:opacity-50"
                  >
                    Reindex
                  </button>
                  <button
                    onClick={() => handleDelete(doc.id)}
                    disabled={busyId === doc.id}
                    className="text-sm text-red-600 hover:text-red-500 disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
