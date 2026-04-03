import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import Dashboard from './pages/Dashboard'
import Invoices from './pages/Invoices'
import Upload from './pages/Upload'
import InvoiceDetail from './pages/InvoiceDetail'
import Alerts from './pages/Alerts'
import Analytics from './pages/Analytics'
import AuditLog from './pages/AuditLog'
import Settings from './pages/Settings'
import Login from './pages/Login'

function getUser() {
  try {
    const u = localStorage.getItem('fradupix_user')
    return u ? JSON.parse(u) : null
  } catch { return null }
}

function hasRole(requiredRoles) {
  const user = getUser()
  if (!user?.role) return false
  return requiredRoles.includes(user.role)
}

function ProtectedRoute({ children }) {
  const token = localStorage.getItem('fradupix_token')
  if (!token) return <Navigate to="/login" replace />
  return children
}

function RoleRoute({ children, roles }) {
  const token = localStorage.getItem('fradupix_token')
  if (!token) return <Navigate to="/login" replace />
  if (!hasRole(roles)) return <Navigate to="/" replace />
  return children
}

function AppLayout({ children, currentPage }) {
  const user = getUser()
  return (
    <div className="app-layout">
      <Sidebar currentPage={currentPage} />
      <div className="main-content">
        <Header user={user} currentPage={currentPage} />
        <div className="page-content">
          {children}
        </div>
      </div>
    </div>
  )
}

function ProtectedPage({ page, children }) {
  return (
    <ProtectedRoute>
      <AppLayout currentPage={page}>
        {children}
      </AppLayout>
    </ProtectedRoute>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<ProtectedPage page="dashboard"><Dashboard /></ProtectedPage>} />
        <Route path="/invoices" element={<ProtectedPage page="invoices"><Invoices /></ProtectedPage>} />
        <Route path="/upload" element={<ProtectedPage page="upload"><Upload /></ProtectedPage>} />
        <Route path="/invoices/:id" element={<ProtectedPage page="invoices"><InvoiceDetail /></ProtectedPage>} />
        <Route path="/alerts" element={<ProtectedPage page="alerts"><Alerts /></ProtectedPage>} />
        <Route path="/analytics" element={<ProtectedPage page="analytics"><Analytics /></ProtectedPage>} />
        <Route path="/audit-log" element={
          <RoleRoute roles={['admin', 'manager', 'auditor']}>
            <AppLayout currentPage="audit-log"><AuditLog /></AppLayout>
          </RoleRoute>
        } />
        <Route path="/settings" element={
          <RoleRoute roles={['admin']}>
            <AppLayout currentPage="settings"><Settings /></AppLayout>
          </RoleRoute>
        } />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
