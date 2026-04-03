import { useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, FileText, Upload, AlertTriangle,
  Shield, BarChart3, Settings, LogOut, HelpCircle,
  Building2, ScrollText, Wrench
} from 'lucide-react'

const navItems = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, path: '/' },
  { id: 'invoices', label: 'Invoices', icon: FileText, path: '/invoices' },
  { id: 'upload', label: 'Upload', icon: Upload, path: '/upload' },
  { id: 'alerts', label: 'Alerts', icon: AlertTriangle, path: '/alerts' },
]

const secondaryItems = [
  { id: 'analytics', label: 'Vendor Analytics', icon: Building2, path: '/analytics' },
  { id: 'audit-log', label: 'Audit Log', icon: ScrollText, path: '/audit-log' },
  { id: 'settings', label: 'Settings', icon: Wrench, path: '/settings' },
]

export default function Sidebar({ currentPage }) {
  const navigate = useNavigate()

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

        <div className="sidebar-section-title">Reports & Admin</div>
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
