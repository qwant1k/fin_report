import { Navigate, Route, Routes } from 'react-router-dom'

import Layout from './components/Layout'
import LoginPage from './pages/Login'
import DashboardPage from './pages/Dashboard'
import UploadPage from './pages/Upload'
import ImportPage from './pages/Import'
import HistoryPage from './pages/History'
import AnalyticsPage from './pages/Analytics'
import PrimaryDataPage from './pages/PrimaryData'
import ReconciliationPage from './pages/Reconciliation'
import PositionsPage from './pages/Positions'
import KasePage from './pages/Kase'
import MbmPage from './pages/Mbm'
import AlertsPage from './pages/Alerts'
import SettingsPage from './pages/Settings'
import AdminPage from './pages/Admin'
import FormulasPage from './pages/Formulas'
import { useAuthStore } from './lib/auth'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthed = useAuthStore((s) => s.isAuthed())
  if (!isAuthed) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AdminOnly({ children }: { children: React.ReactNode }) {
  const isAdmin = useAuthStore((s) => s.isAdmin())
  if (!isAdmin) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/import" element={<AdminOnly><ImportPage /></AdminOnly>} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/primary-data" element={<PrimaryDataPage />} />
        <Route path="/reconciliation" element={<ReconciliationPage />} />
        <Route path="/positions" element={<PositionsPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/kase" element={<KasePage />} />
        <Route path="/mbm" element={<MbmPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/formulas" element={<AdminOnly><FormulasPage /></AdminOnly>} />
        <Route path="/admin" element={<AdminOnly><AdminPage /></AdminOnly>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
