import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { dashboardAPI } from '../services/api'

const initialAlerts = []

const timeAgo = (d) => {
  const s = Math.floor((Date.now()-new Date(d))/1000)
  if(s<60) return `${s}s ago`
  if(s<3600) return `${Math.floor(s/60)}m ago`
  if(s<86400) return `${Math.floor(s/3600)}h ago`
  return `${Math.floor(s/86400)}d ago`
}

const typeIcons = { forgery:'🔍', duplicate:'📋', anomaly:'📊' }

export default function Alerts() {
  const [alerts, setAlerts] = useState(initialAlerts)
  const navigate = useNavigate()

  useEffect(() => {
    dashboardAPI.getAlerts({ page_size: 50 })
      .then(r => setAlerts(r.data.alerts || []))
      .catch(err => console.error("Failed to load alerts:", err))
  }, [])

  const critical = alerts.filter(a => a.risk_level==='critical')
  const high = alerts.filter(a => a.risk_level==='high')

  return (
    <div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:16,marginBottom:24}}>
        <div className="stat-card danger">
          <div className="stat-info">
            <div className="stat-label">Critical Alerts</div>
            <div className="stat-value">{critical.length}</div>
          </div>
        </div>
        <div className="stat-card warning">
          <div className="stat-info">
            <div className="stat-label">High Risk Alerts</div>
            <div className="stat-value">{high.length}</div>
          </div>
        </div>
        <div className="stat-card primary">
          <div className="stat-info">
            <div className="stat-label">Total Active</div>
            <div className="stat-value">{alerts.length}</div>
          </div>
        </div>
      </div>

      {critical.length > 0 && (
        <div className="card" style={{marginBottom:16}}>
          <div className="card-header">
            <div className="card-title">🚨 Critical Alerts</div>
          </div>
          {critical.map((a,i) => (
            <div key={a.id} className="alert-item animate-slide-up" style={{animationDelay:`${i*60}ms`}} onClick={() => navigate(`/invoices/${a.invoice_id}`)}>
              <span className="alert-dot critical"/>
              <div className="alert-content">
                <div className="alert-title">{typeIcons[a.alert_type]} {a.filename}</div>
                <div className="alert-desc">{a.description}</div>
              </div>
              <div style={{textAlign:'right',flexShrink:0}}>
                <span className="badge badge-critical">{a.risk_score}</span>
                <div className="alert-time">{timeAgo(a.created_at)}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {high.length > 0 && (
        <div className="card">
          <div className="card-header">
            <div className="card-title">⚠️ High Risk Alerts</div>
          </div>
          {high.map((a,i) => (
            <div key={a.id} className="alert-item animate-slide-up" style={{animationDelay:`${i*60}ms`}} onClick={() => navigate(`/invoices/${a.invoice_id}`)}>
              <span className="alert-dot high"/>
              <div className="alert-content">
                <div className="alert-title">{typeIcons[a.alert_type]} {a.filename}</div>
                <div className="alert-desc">{a.description}</div>
              </div>
              <div style={{textAlign:'right',flexShrink:0}}>
                <span className="badge badge-high">{a.risk_score}</span>
                <div className="alert-time">{timeAgo(a.created_at)}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {alerts.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">✅</div>
          <h3>No Active Alerts</h3>
          <p>All invoices are within acceptable risk thresholds</p>
        </div>
      )}
    </div>
  )
}
