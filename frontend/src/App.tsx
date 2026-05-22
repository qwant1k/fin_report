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
import ReportsPage from './pages/Reports'
import SecuritiesPage from './pages/Securities'
import RiskReportPage from './pages/RiskReport'
import DataEditorPage from './pages/DataEditor'
import { useAuthStore } from './lib/auth'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthed = useAuthStore((s) => s.isAuthed())
  if (!isAuthed) return <Navigate to="/login" replace />
  return <>{children}</>
}

function PermissionRoute({ permission, children }: { permission: string; children: React.ReactNode }) {
  const allowed = useAuthStore((s) => s.can(permission))
  if (!allowed) {
    return (
      <div className="card p-8 text-center text-slate-500">
        Нет прав для просмотра этой страницы.
      </div>
    )
  }
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route path="/" element={<PermissionRoute permission="page.dashboard"><DashboardPage /></PermissionRoute>} />
        <Route path="/upload" element={<PermissionRoute permission="page.upload"><UploadPage /></PermissionRoute>} />
        <Route path="/import" element={<PermissionRoute permission="page.import"><ImportPage /></PermissionRoute>} />
        <Route path="/analytics" element={<PermissionRoute permission="page.analytics"><AnalyticsPage /></PermissionRoute>} />
        <Route path="/primary-data" element={<PermissionRoute permission="page.primary_data"><PrimaryDataPage /></PermissionRoute>} />
        <Route path="/reconciliation" element={<PermissionRoute permission="page.reconciliation"><ReconciliationPage /></PermissionRoute>} />
        <Route path="/positions" element={<PermissionRoute permission="page.positions"><PositionsPage /></PermissionRoute>} />
        <Route path="/history" element={<PermissionRoute permission="page.history"><HistoryPage /></PermissionRoute>} />
        <Route path="/kase" element={<PermissionRoute permission="page.kase"><KasePage /></PermissionRoute>} />
        <Route path="/mbm" element={<PermissionRoute permission="page.mbm"><MbmPage /></PermissionRoute>} />
        <Route path="/alerts" element={<PermissionRoute permission="page.alerts"><AlertsPage /></PermissionRoute>} />
        <Route path="/reports" element={<PermissionRoute permission="page.reports"><ReportsPage /></PermissionRoute>} />
        <Route path="/securities" element={<PermissionRoute permission="page.securities"><SecuritiesPage /></PermissionRoute>} />
        <Route path="/risk-report" element={<PermissionRoute permission="page.risk_report"><RiskReportPage /></PermissionRoute>} />
        <Route path="/data-editor" element={<PermissionRoute permission="page.data_editor"><DataEditorPage /></PermissionRoute>} />
        <Route path="/settings" element={<PermissionRoute permission="page.settings"><SettingsPage /></PermissionRoute>} />
        <Route path="/formulas" element={<PermissionRoute permission="page.formulas"><FormulasPage /></PermissionRoute>} />
        <Route path="/admin" element={<PermissionRoute permission="page.admin"><AdminPage /></PermissionRoute>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
