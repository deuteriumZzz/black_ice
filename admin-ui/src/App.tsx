import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '@/components/Layout'
import { useAuth } from '@/contexts/AuthContext'
import { LiveFeedProvider } from '@/contexts/LiveFeedContext'
import { AuditPage } from '@/pages/Audit'
import { DashboardPage } from '@/pages/Dashboard'
import { IdentitiesPage } from '@/pages/Identities'
import { LoginPage } from '@/pages/Login'

function ProtectedLayout() {
  const { status } = useAuth()
  if (status === 'loading') return null
  if (status === 'unauthenticated') return <Navigate to="/login" replace />
  return (
    <LiveFeedProvider>
      <Layout />
    </LiveFeedProvider>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/identities" element={<IdentitiesPage />} />
        <Route path="/audit" element={<AuditPage />} />
      </Route>
    </Routes>
  )
}
