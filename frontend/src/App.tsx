import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '@/auth/AuthContext'
import { ProtectedRoute } from '@/auth/ProtectedRoute'
import { Layout } from '@/components/Layout'
import { CallDetailPage } from '@/pages/CallDetailPage'
import { CallsPage } from '@/pages/CallsPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { FaqsPage } from '@/pages/FaqsPage'
import { HoursPage } from '@/pages/HoursPage'
import { KnowledgePage } from '@/pages/KnowledgePage'
import { LoginPage } from '@/pages/LoginPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { ReservationsPage } from '@/pages/ReservationsPage'

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="calls" element={<CallsPage />} />
            <Route path="calls/:callId" element={<CallDetailPage />} />
            <Route path="reservations" element={<ReservationsPage />} />
            <Route path="faqs" element={<FaqsPage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route path="hours" element={<HoursPage />} />
            <Route path="profile" element={<ProfilePage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  )
}

export default App
