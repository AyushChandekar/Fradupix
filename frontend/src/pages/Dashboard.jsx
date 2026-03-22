import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FileText, ShieldAlert, CheckCircle2, XCircle,
  TrendingUp, AlertTriangle, Upload, Eye, ArrowUpRight, ArrowDownRight
} from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell
} from 'recharts'
import { dashboardAPI } from '../services/api'

const initialStats = {
  total_invoices: 0,
  flagged_invoices: 0,
  approved_invoices: 0,
  rejected_invoices: 0,
  avg_risk_score: 0,
  high_risk_count: 0,
  critical_count: 0,
  total_amount_processed: 0,
  duplicates_detected: 0,
  invoices_today: 0,
}

const initialTimeline = []
const initialRiskDist = { low: 0, medium: 0, high: 0, critical: 0 }
const initialAlerts = []

const RISK_COLORS = ['#10b981', '#f59e0b', '#f43f5e', '#dc2626']

const formatCurrency = (n) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n)

const timeAgo = (date) => {
  const seconds = Math.floor((Date.now() - new Date(date)) / 1000)
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

function StatCard({ label, value, icon: Icon, variant = 'primary', change, changeDir }) {
  return (
    <div className={`stat-card ${variant} animate-slide-up`}>
      <div className="stat-info">
        <div className="stat-label">{label}</div>
        <div className="stat-value">{value}</div>
        {change && (
          <span className={`stat-change ${changeDir}`}>
            {changeDir === 'up' ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
            {change}
          </span>
        )}
      </div>
      <div className="stat-icon">
        <Icon size={24} />
      </div>
    </div>
  )
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: 'var(--surface-2)',
      border: '1px solid var(--border-default)',
      borderRadius: 'var(--radius-md)',
      padding: '12px 16px',
      fontSize: 13,
    }}>
      <div style={{ color: 'var(--text-secondary)', marginBottom: 4 }}>{label}</div>
      {payload.map((entry, i) => (
        <div key={i} style={{ color: entry.color, fontWeight: 600 }}>
          {entry.name}: {entry.value}
        </div>
      ))}
    </div>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState(initialStats)
  const [timeline, setTimeline] = useState(initialTimeline)
  const [riskDist, setRiskDist] = useState(initialRiskDist)
  const [alerts, setAlerts] = useState(initialAlerts)
  const navigate = useNavigate()

  useEffect(() => {
    const loadData = async () => {
      try {
        const [statsRes, timelineRes, riskRes, alertsRes] = await Promise.all([
          dashboardAPI.getStats(),
          dashboardAPI.getTimeline(),
          dashboardAPI.getRiskDistribution(),
          dashboardAPI.getAlerts(),
        ])
        setStats(statsRes.data)
        setTimeline(timelineRes.data)
        setRiskDist(riskRes.data)
        setAlerts(alertsRes.data.alerts || [])
      } catch (err) {
        console.error("Failed to load dashboard data:", err)
      }
    }
    loadData()
  }, [])

  const riskPieData = Object.entries(riskDist).map(([key, value]) => ({
    name: key.charAt(0).toUpperCase() + key.slice(1),
    value,
  }))

  return (
    <div>
      {/* Stats Grid */}
      <div className="stats-grid">
        <StatCard
          label="Total Invoices"
          value={stats.total_invoices.toLocaleString()}
          icon={FileText}
          variant="primary"
          change="+12.5%"
          changeDir="up"
        />
        <StatCard
          label="Flagged for Review"
          value={stats.flagged_invoices}
          icon={ShieldAlert}
          variant="danger"
          change={`${stats.critical_count} critical`}
          changeDir="up"
        />
        <StatCard
          label="Approved"
          value={stats.approved_invoices.toLocaleString()}
          icon={CheckCircle2}
          variant="success"
          change="+8.3%"
          changeDir="up"
        />
        <StatCard
          label="Amount Processed"
          value={formatCurrency(stats.total_amount_processed)}
          icon={TrendingUp}
          variant="warning"
          change="Last 30 days"
        />
      </div>

      {/* Charts */}
      <div className="charts-grid">
        {/* Timeline Chart */}
        <div className="chart-container">
          <div className="card-header">
            <div>
              <div className="card-title">Invoice Processing Timeline</div>
              <div className="card-subtitle">Daily volume and flagged invoices</div>
            </div>
            <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#6366f1' }} />
                Total
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#f43f5e' }} />
                Flagged
              </span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={timeline}>
              <defs>
                <linearGradient id="gradientTotal" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradientFlagged" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
              <XAxis
                dataKey="date"
                stroke="var(--text-tertiary)"
                fontSize={11}
                tickFormatter={(v) => v.split('-').slice(1).join('/')}
              />
              <YAxis stroke="var(--text-tertiary)" fontSize={11} />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="total"
                stroke="#6366f1"
                fill="url(#gradientTotal)"
                strokeWidth={2}
                name="Total"
              />
              <Area
                type="monotone"
                dataKey="flagged"
                stroke="#f43f5e"
                fill="url(#gradientFlagged)"
                strokeWidth={2}
                name="Flagged"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Risk Distribution */}
        <div className="chart-container">
          <div className="card-header">
            <div>
              <div className="card-title">Risk Distribution</div>
              <div className="card-subtitle">Invoice risk classification</div>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={riskPieData}
                cx="50%"
                cy="50%"
                innerRadius={55}
                outerRadius={80}
                paddingAngle={3}
                dataKey="value"
              >
                {riskPieData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={RISK_COLORS[index]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: 'var(--surface-2)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: 13,
                }}
              />
            </PieChart>
          </ResponsiveContainer>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 8 }}>
            {riskPieData.map((entry, i) => (
              <div key={entry.name} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: RISK_COLORS[i] }} />
                <span style={{ color: 'var(--text-secondary)' }}>{entry.name}: {entry.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Alerts & Quick Actions */}
      <div className="charts-grid">
        {/* Recent Alerts */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">🚨 Active Fraud Alerts</div>
              <div className="card-subtitle">{alerts.length} alerts require attention</div>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/alerts')}>
              View All <ArrowUpRight size={14} />
            </button>
          </div>
          {alerts.slice(0, 5).map((alert) => (
            <div key={alert.id} className="alert-item" onClick={() => navigate(`/invoices/${alert.id}`)}>
              <span className={`alert-dot ${alert.risk_level}`} />
              <div className="alert-content">
                <div className="alert-title">{alert.filename}</div>
                <div className="alert-desc">{alert.description}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span className={`badge badge-${alert.risk_level}`}>
                  {alert.risk_score}
                </span>
                <div className="alert-time">{timeAgo(alert.created_at)}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Quick Stats */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">Quick Actions</div>
              <div className="card-subtitle">Common tasks</div>
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <button className="btn btn-primary" onClick={() => navigate('/upload')} style={{ width: '100%' }}>
              <Upload size={18} /> Upload Invoices
            </button>
            <button className="btn btn-secondary" onClick={() => navigate('/invoices?status=flagged')} style={{ width: '100%' }}>
              <ShieldAlert size={18} /> Review Flagged ({stats.flagged_invoices})
            </button>
            <button className="btn btn-secondary" onClick={() => navigate('/invoices')} style={{ width: '100%' }}>
              <Eye size={18} /> View All Invoices
            </button>
          </div>

          <div style={{ marginTop: 24 }}>
            <div className="card-title" style={{ marginBottom: 12 }}>Today's Summary</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                <span style={{ color: 'var(--text-secondary)' }}>Processed today</span>
                <span style={{ fontWeight: 600 }}>{stats.invoices_today}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                <span style={{ color: 'var(--text-secondary)' }}>Duplicates found</span>
                <span style={{ fontWeight: 600, color: 'var(--warning-400)' }}>{stats.duplicates_detected}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                <span style={{ color: 'var(--text-secondary)' }}>Avg risk score</span>
                <span style={{ fontWeight: 600 }}>{stats.avg_risk_score}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                <span style={{ color: 'var(--text-secondary)' }}>Critical alerts</span>
                <span style={{ fontWeight: 600, color: 'var(--danger-400)' }}>{stats.critical_count}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
