import { useEffect, useState, type FormEvent } from 'react'
import { extractErrorMessage } from '@/api/client'
import { getRestaurant, updateRestaurant } from '@/api/restaurants'
import type { Restaurant } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { ErrorBanner, LoadingState, PageHeader } from '@/components/Feedback'

type FormState = Pick<
  Restaurant,
  | 'name'
  | 'description'
  | 'address'
  | 'city'
  | 'state'
  | 'postal_code'
  | 'phone_number'
  | 'email'
  | 'website'
  | 'timezone'
  | 'transfer_number'
  | 'menu_url'
  | 'ai_greeting'
>

function toFormState(restaurant: Restaurant): FormState {
  const {
    name,
    description,
    address,
    city,
    state,
    postal_code,
    phone_number,
    email,
    website,
    timezone,
    transfer_number,
    menu_url,
    ai_greeting,
  } = restaurant
  return {
    name,
    description,
    address,
    city,
    state,
    postal_code,
    phone_number,
    email,
    website,
    timezone,
    transfer_number,
    menu_url,
    ai_greeting,
  }
}

const FIELDS: { key: keyof FormState; label: string; type?: 'text' | 'textarea' }[] = [
  { key: 'name', label: 'Restaurant name' },
  { key: 'description', label: 'Description', type: 'textarea' },
  { key: 'address', label: 'Address' },
  { key: 'city', label: 'City' },
  { key: 'state', label: 'State' },
  { key: 'postal_code', label: 'Postal code' },
  { key: 'phone_number', label: 'Business phone (receives notifications)' },
  { key: 'email', label: 'Business email (receives notifications)' },
  { key: 'website', label: 'Website' },
  { key: 'timezone', label: 'Timezone (IANA, e.g. America/New_York)' },
  { key: 'transfer_number', label: 'Transfer number (for human handoff)' },
  { key: 'menu_url', label: 'Menu URL' },
  { key: 'ai_greeting', label: 'AI greeting (spoken at the start of every call)', type: 'textarea' },
]

export function ProfilePage() {
  const { user } = useAuth()
  const restaurantId = user?.restaurant_id ?? ''
  const [form, setForm] = useState<FormState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!restaurantId) return
    getRestaurant(restaurantId)
      .then((restaurant) => setForm(toFormState(restaurant)))
      .catch((err) => setError(extractErrorMessage(err)))
  }, [restaurantId])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!form) return
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await updateRestaurant(restaurantId, form)
      setForm(toFormState(updated))
      setSavedAt(Date.now())
    } catch (err) {
      setSaveError(extractErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  if (error) return <ErrorBanner message={error} />
  if (!form) return <LoadingState />

  return (
    <div>
      <PageHeader title="Restaurant Profile" description="What the AI receptionist knows about you." />

      <form
        onSubmit={handleSubmit}
        className="max-w-2xl space-y-4 rounded-xl border border-gray-200 bg-white p-6"
      >
        {FIELDS.map(({ key, label, type }) => (
          <div key={key}>
            <label className="block text-sm font-medium text-gray-700" htmlFor={key}>
              {label}
            </label>
            {type === 'textarea' ? (
              <textarea
                id={key}
                rows={3}
                value={form[key] ?? ''}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            ) : (
              <input
                id={key}
                value={form[key] ?? ''}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            )}
          </div>
        ))}

        {saveError && <ErrorBanner message={saveError} />}
        {savedAt && <p className="text-sm text-green-600">Saved.</p>}

        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </form>
    </div>
  )
}
