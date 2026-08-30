import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/calls', label: 'Calls' },
  { to: '/reservations', label: 'Reservations' },
  { to: '/faqs', label: 'FAQs' },
  { to: '/knowledge', label: 'Knowledge Base' },
  { to: '/hours', label: 'Hours' },
  { to: '/profile', label: 'Restaurant Profile' },
]

function navLinkClasses(isActive: boolean): string {
  return [
    'block rounded-lg px-3 py-2 text-sm font-medium transition-colors',
    isActive ? 'bg-indigo-600 text-white' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
  ].join(' ')
}

export function Layout() {
  const { user, logout } = useAuth()

  return (
    <div className="flex min-h-screen bg-gray-50">
      <aside className="flex w-64 flex-shrink-0 flex-col border-r border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-4 py-5">
          <h1 className="text-lg font-bold text-gray-900">AI Receptionist</h1>
          <p className="text-xs text-gray-500">Admin Dashboard</p>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-4">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => navLinkClasses(isActive)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-gray-200 p-4">
          <p className="truncate text-sm font-medium text-gray-900">{user?.email}</p>
          <p className="text-xs capitalize text-gray-500">{user?.role.replace(/_/g, ' ')}</p>
          <button
            onClick={logout}
            className="mt-3 w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Log out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl px-6 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
