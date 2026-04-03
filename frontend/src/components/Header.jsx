import { Search, Bell, Moon } from 'lucide-react'

const pageTitles = {
  dashboard: 'Dashboard',
  invoices: 'Invoice Manager',
  upload: 'Upload Invoices',
  alerts: 'Fraud Alerts',
  analytics: 'Vendor Analytics',
  'audit-log': 'Audit Log',
  settings: 'Settings',
}

const roleBadgeColors = {
  admin: { bg: 'rgba(220,38,38,.15)', color: '#ef4444' },
  manager: { bg: 'rgba(99,102,241,.15)', color: '#6366f1' },
  auditor: { bg: 'rgba(245,158,11,.15)', color: '#f59e0b' },
  analyst: { bg: 'rgba(16,185,129,.15)', color: '#10b981' },
  viewer: { bg: 'rgba(148,163,184,.15)', color: '#94a3b8' },
}

export default function Header({ user, currentPage }) {
  const initials = user?.full_name
    ? user.full_name.split(' ').map(n => n[0]).join('').toUpperCase()
    : user?.username?.[0]?.toUpperCase() || 'U'

  return (
    <header className="header">
      <div className="header-left">
        <div>
          <h2>{pageTitles[currentPage] || 'Dashboard'}</h2>
          <div className="header-breadcrumb">
            InvoiceFirewall / {pageTitles[currentPage] || 'Dashboard'}
          </div>
        </div>
      </div>
      <div className="header-right">
        <div className="header-search">
          <Search className="header-search-icon" size={16} />
          <input type="text" placeholder="Search invoices, vendors..." />
        </div>
        <button className="header-btn">
          <Moon size={18} />
        </button>
        <button className="header-btn">
          <Bell size={18} />
          <span className="notification-dot" />
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div className="user-avatar" title={user?.full_name || user?.username}>
            {initials}
          </div>
          {user?.role && (
            <span style={{
              fontSize: 11,
              fontWeight: 600,
              padding: '2px 8px',
              borderRadius: 'var(--radius-sm)',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
              background: (roleBadgeColors[user.role] || roleBadgeColors.viewer).bg,
              color: (roleBadgeColors[user.role] || roleBadgeColors.viewer).color,
            }}>
              {user.role}
            </span>
          )}
        </div>
      </div>
    </header>
  )
}
