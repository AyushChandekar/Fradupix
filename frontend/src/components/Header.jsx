import { Search, Bell, Moon } from 'lucide-react'

const pageTitles = {
  dashboard: 'Dashboard',
  invoices: 'Invoice Manager',
  upload: 'Upload Invoices',
  alerts: 'Fraud Alerts',
  analytics: 'Analytics',
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
            Fradupix / {pageTitles[currentPage] || 'Dashboard'}
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
        <div className="user-avatar" title={user?.full_name || user?.username}>
          {initials}
        </div>
      </div>
    </header>
  )
}
