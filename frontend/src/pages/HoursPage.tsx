import { useEffect, useState } from 'react'
import { extractErrorMessage } from '@/api/client'
import { getHours, replaceHours } from '@/api/hours'
import type { HoursEntry } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { ErrorBanner, LoadingState, PageHeader } from '@/components/Feedback'
import { dayName } from '@/lib/format'

function defaultWeek(): HoursEntry[] {
  return Array.from({ length: 7 }, (_, day) => ({
    day_of_week: day,
    opening_time: '09:00',
    closing_time: '17:00',
    is_closed: false,
  }))
}

export function HoursPage() {
  const { user } = useAuth()
  const restaurantId = user?.restaurant_id ?? ''
  const [week, setWeek] = useState<HoursEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!restaurantId) return
    getHours(restaurantId)
      .then((existing) => {
        const merged = defaultWeek()
        for (const entry of existing) {
          merged[entry.day_of_week] = entry
        }
        setWeek(merged)
      })
      .catch((err) => setError(extractErrorMessage(err)))
  }, [restaurantId])

  function updateDay(dayOfWeek: number, patch: Partial<HoursEntry>) {
    if (!week) return
    setWeek(week.map((entry) => (entry.day_of_week === dayOfWeek ? { ...entry, ...patch } : entry)))
  }

  async function handleSave() {
    if (!week) return
    setSaving(true)
    setSaveError(null)
    try {
      await replaceHours(restaurantId, week)
      setSavedAt(Date.now())
    } catch (err) {
      setSaveError(extractErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  if (error) return <ErrorBanner message={error} />
  if (!week) return <LoadingState />

  return (
    <div>
      <PageHeader title="Operating Hours" description="What the AI tells callers when asked when you're open." />

      <div className="max-w-3xl overflow-hidden rounded-xl border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-4 py-3">Day</th>
              <th className="px-4 py-3">Open</th>
              <th className="px-4 py-3">Close</th>
              <th className="px-4 py-3">Closed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {week.map((entry) => (
              <tr key={entry.day_of_week}>
                <td className="px-4 py-3 font-medium text-gray-900">{dayName(entry.day_of_week)}</td>
                <td className="px-4 py-3">
                  <input
                    type="time"
                    value={entry.opening_time}
                    disabled={entry.is_closed}
                    onChange={(e) => updateDay(entry.day_of_week, { opening_time: e.target.value })}
                    className="rounded-lg border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-100 disabled:text-gray-400"
                  />
                </td>
                <td className="px-4 py-3">
                  <input
                    type="time"
                    value={entry.closing_time}
                    disabled={entry.is_closed}
                    onChange={(e) => updateDay(entry.day_of_week, { closing_time: e.target.value })}
                    className="rounded-lg border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-100 disabled:text-gray-400"
                  />
                </td>
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={entry.is_closed}
                    onChange={(e) => updateDay(entry.day_of_week, { is_closed: e.target.checked })}
                    className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 max-w-3xl">
        {saveError && <ErrorBanner message={saveError} />}
        {savedAt && <p className="mb-2 text-sm text-green-600">Saved.</p>}
        <button
          onClick={handleSave}
          disabled={saving}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save hours'}
        </button>
      </div>
    </div>
  )
}
