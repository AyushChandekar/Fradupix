import { useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, FileText, Upload, AlertTriangle,
  Shield, BarChart3, Settings, LogOut, HelpCircle
} from 'lucide-react'

const navItems = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, path: '/' },
  { id: 'invoices', label: 'Invoices', icon: FileText, path: '/invoices' },
  { id: 'upload', label: 'Upload', icon: Upload, path: '/upload' },
  { id: 'alerts', label: 'Alerts', icon: AlertTriangle, path: '/alerts', badge: null },
]

const secondaryItems = [
  { id: 'analytics', label: 'Analytics', icon: BarChart3, path: '/' },
  { id: 'security', label: 'Security', icon: Shield, path: '/' },
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
          <h1>Fradupix</h1>
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
            {item.badge !== undefined && item.badge !== null && (
              <span className="nav-badge">{item.badge}</span>
            )}
          </button>
        ))}

        <div className="sidebar-section-title">Reports</div>
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

        <button className="nav-item" onClick={() => {}}>
          <HelpCircle className="nav-icon" size={20} />
          <span>Help & Docs</span>
        </button>
        <button className="nav-item" onClick={() => {}}>
          <Settings className="nav-icon" size={20} />
          <span>Settings</span>
        </button>
        <button className="nav-item" onClick={handleLogout} style={{ color: 'var(--danger-400)' }}>
          <LogOut className="nav-icon" size={20} />
          <span>Logout</span>
        </button>
      </nav>
    </aside>
  )
}
