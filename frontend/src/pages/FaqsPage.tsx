import { useEffect, useState, type FormEvent } from 'react'
import { extractErrorMessage } from '@/api/client'
import { createFaq, deleteFaq, listFaqs, updateFaq } from '@/api/faqs'
import type { FAQ } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { EmptyState, ErrorBanner, LoadingState, PageHeader } from '@/components/Feedback'

export function FaqsPage() {
  const { user } = useAuth()
  const restaurantId = user?.restaurant_id ?? ''
  const [faqs, setFaqs] = useState<FAQ[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [category, setCategory] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function load() {
    if (!restaurantId) return
    listFaqs(restaurantId)
      .then(setFaqs)
      .catch((err) => setError(extractErrorMessage(err)))
  }

  useEffect(load, [restaurantId])

  function resetForm() {
    setQuestion('')
    setAnswer('')
    setCategory('')
    setEditingId(null)
  }

  function startEdit(faq: FAQ) {
    setEditingId(faq.id)
    setQuestion(faq.question)
    setAnswer(faq.answer)
    setCategory(faq.category ?? '')
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFormError(null)
    try {
      if (editingId) {
        await updateFaq(restaurantId, editingId, { question, answer, category: category || null })
      } else {
        await createFaq(restaurantId, { question, answer, category: category || undefined })
      }
      resetForm()
      load()
    } catch (err) {
      setFormError(extractErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete(faqId: string) {
    try {
      await deleteFaq(restaurantId, faqId)
      load()
    } catch (err) {
      setError(extractErrorMessage(err))
    }
  }

  return (
    <div>
      <PageHeader
        title="Frequently Asked Questions"
        description="Grounds the AI's answers to common caller questions — never improvised."
      />

      <form
        onSubmit={handleSubmit}
        className="mb-6 max-w-2xl space-y-3 rounded-xl border border-gray-200 bg-white p-5"
      >
        <h3 className="font-semibold text-gray-900">{editingId ? 'Edit FAQ' : 'Add a new FAQ'}</h3>
        <div>
          <label className="block text-sm font-medium text-gray-700" htmlFor="question">
            Question
          </label>
          <input
            id="question"
            required
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700" htmlFor="answer">
            Answer
          </label>
          <textarea
            id="answer"
            required
            rows={2}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700" htmlFor="category">
            Category (optional)
          </label>
          <input
            id="category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        {formError && <ErrorBanner message={formError} />}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? 'Saving…' : editingId ? 'Update FAQ' : 'Add FAQ'}
          </button>
          {editingId && (
            <button
              type="button"
              onClick={resetForm}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
          )}
        </div>
      </form>

      {error && <ErrorBanner message={error} />}

      {faqs === null ? (
        <LoadingState />
      ) : faqs.length === 0 ? (
        <EmptyState message="No FAQs yet — add one above." />
      ) : (
        <ul className="max-w-2xl space-y-3">
          {faqs.map((faq) => (
            <li key={faq.id} className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-gray-900">{faq.question}</p>
                  <p className="mt-1 text-sm text-gray-600">{faq.answer}</p>
                  {faq.category && (
                    <span className="mt-2 inline-block rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {faq.category}
                    </span>
                  )}
                </div>
                <div className="flex flex-shrink-0 gap-2">
                  <button
                    onClick={() => startEdit(faq)}
                    className="text-sm text-indigo-600 hover:text-indigo-500"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => handleDelete(faq.id)}
                    className="text-sm text-red-600 hover:text-red-500"
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
