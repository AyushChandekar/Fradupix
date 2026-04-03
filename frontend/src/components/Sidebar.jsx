import { useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, FileText, Upload, AlertTriangle,
  Shield, BarChart3, Settings, LogOut, HelpCircle,
  Building2, ScrollText, Wrench
} from 'lucide-react'

// Role access mapping:
// viewer:  Dashboard, Invoices (read-only), Alerts
// analyst: Dashboard, Invoices, Upload, Alerts, Vendor Analytics
// auditor: All except Settings
// manager: All
// admin:   All
const allNavItems = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, path: '/', roles: ['viewer', 'analyst', 'auditor', 'manager', 'admin'] },
  { id: 'invoices', label: 'Invoices', icon: FileText, path: '/invoices', roles: ['viewer', 'analyst', 'auditor', 'manager', 'admin'] },
  { id: 'upload', label: 'Upload', icon: Upload, path: '/upload', roles: ['analyst', 'auditor', 'manager', 'admin'] },
  { id: 'alerts', label: 'Alerts', icon: AlertTriangle, path: '/alerts', roles: ['viewer', 'analyst', 'auditor', 'manager', 'admin'] },
]

const allSecondaryItems = [
  { id: 'analytics', label: 'Vendor Analytics', icon: Building2, path: '/analytics', roles: ['analyst', 'auditor', 'manager', 'admin'] },
  { id: 'audit-log', label: 'Audit Log', icon: ScrollText, path: '/audit-log', roles: ['auditor', 'manager', 'admin'] },
  { id: 'settings', label: 'Settings', icon: Wrench, path: '/settings', roles: ['admin'] },
]

function getUserRole() {
  try {
    const u = localStorage.getItem('fradupix_user')
    return u ? JSON.parse(u).role : null
  } catch { return null }
}

export default function Sidebar({ currentPage }) {
  const navigate = useNavigate()
  const role = getUserRole() || 'viewer'
  const navItems = allNavItems.filter(item => item.roles.includes(role))
  const secondaryItems = allSecondaryItems.filter(item => item.roles.includes(role))

  const handleLogout = () => {
    localStorage.removeItem('fradupix_token')
    localStorage.removeItem('fradupix_user')
    navigate('/login')
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">🛡️</div>
        <div className="sidebar-brand-text">
          <h1>InvoiceFirewall</h1>
          <span>Fraud Detection</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        <div className="sidebar-section-title">Main Menu</div>
        {navItems.map(item => (
          <button
            key={item.id}
            className={`nav-item ${currentPage === item.id ? 'active' : ''}`}
            onClick={() => navigate(item.path)}
          >
            <item.icon className="nav-icon" size={20} />
            <span>{item.label}</span>
          </button>
        ))}

        {secondaryItems.length > 0 && <div className="sidebar-section-title">Reports & Admin</div>}
        {secondaryItems.map(item => (
          <button
            key={item.id}
            className={`nav-item ${currentPage === item.id ? 'active' : ''}`}
            onClick={() => navigate(item.path)}
          >
            <item.icon className="nav-icon" size={20} />
            <span>{item.label}</span>
          </button>
        ))}

        <div style={{ flex: 1 }} />

        <button className="nav-item" onClick={handleLogout} style={{ color: 'var(--danger-400)' }}>
          <LogOut className="nav-icon" size={20} />
          <span>Logout</span>
        </button>
      </nav>
    </aside>
  )
}
