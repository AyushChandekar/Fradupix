import { useState, useEffect } from 'react'
import { dashboardAPI } from '../services/api'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { Building2, TrendingUp, AlertTriangle, DollarSign } from 'lucide-react'

const RISK_COLORS = { low: '#22c55e', medium: '#f59e0b', high: '#ef4444', critical: '#dc2626' }

export default function Analytics() {
  const [vendors, setVendors] = useState([])
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(90)

  useEffect(() => {
    setLoading(true)
    dashboardAPI.getVendorAnalytics({ days, page: 1, page_size: 50 })
      .then(res => setVendors(res.data.vendors || []))
      .catch(() => setVendors([]))
      .finally(() => setLoading(false))
  }, [days])

  const chartData = vendors.slice(0, 15).map(v => ({
    name: v.vendor_name?.substring(0, 20) || 'Unknown',
    risk: v.avg_risk_score,
    invoices: v.total_invoices,
    flagged: v.flagged_count,
  }))

  const getRiskColor = (score) => {
    if (score > 85) return RISK_COLORS.critical
    if (score > 60) return RISK_COLORS.high
    if (score > 30) return RISK_COLORS.medium
    return RISK_COLORS.low
  }

  return (
    <div className="page-analytics">
      <div className="page-header">
        <h2><Building2 size={24} /> Vendor Risk Analytics</h2>
        <select value={days} onChange={e => setDays(Number(e.target.value))} className="select-input">
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={180}>Last 6 months</option>
          <option value={365}>Last year</option>
        </select>
      </div>

      {/* Summary Cards */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginBottom: '1.5rem' }}>
        <div className="stat-card">
          <Building2 size={20} />
          <div><div className="stat-value">{vendors.length}</div><div className="stat-label">Total Vendors</div></div>
        </div>
        <div className="stat-card">
          <AlertTriangle size={20} />
          <div><div className="stat-value">{vendors.filter(v => v.flag_rate > 20).length}</div><div className="stat-label">High-Risk Vendors</div></div>
        </div>
        <div className="stat-card">
          <TrendingUp size={20} />
          <div><div className="stat-value">{vendors.length > 0 ? (vendors.reduce((a, v) => a + v.avg_risk_score, 0) / vendors.length).toFixed(1) : 0}</div><div className="stat-label">Avg Risk Score</div></div>
        </div>
        <div className="stat-card">
          <DollarSign size={20} />
          <div><div className="stat-value">${vendors.reduce((a, v) => a + v.total_amount, 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div><div className="stat-label">Total Volume</div></div>
        </div>
      </div>

      {/* Risk Chart */}
      {chartData.length > 0 && (
        <div className="card" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
          <h3 style={{ marginBottom: '1rem' }}>Vendor Risk Ranking (Top 15)</h3>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 100 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
              <XAxis type="number" domain={[0, 100]} stroke="#9ca3af" />
              <YAxis dataKey="name" type="category" stroke="#9ca3af" width={100} tick={{ fontSize: 12 }} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }} />
              <Bar dataKey="risk" name="Avg Risk Score" radius={[0, 4, 4, 0]}>
                {chartData.map((entry, idx) => (
                  <Cell key={idx} fill={getRiskColor(entry.risk)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Vendor Table */}
      <div className="card" style={{ padding: '1.5rem' }}>
        <h3 style={{ marginBottom: '1rem' }}>Vendor Details</h3>
        {loading ? (
          <div className="loading">Loading vendor data...</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Vendor</th>
                <th>Invoices</th>
                <th>Flagged</th>
                <th>Flag Rate</th>
                <th>Avg Risk</th>
                <th>Total Amount</th>
              </tr>
            </thead>
            <tbody>
              {vendors.map((v, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 600 }}>{v.vendor_name || 'Unknown'}</td>
                  <td>{v.total_invoices}</td>
                  <td><span style={{ color: v.flagged_count > 0 ? '#ef4444' : '#22c55e' }}>{v.flagged_count}</span></td>
                  <td>
                    <span className={`risk-badge risk-${v.flag_rate > 20 ? 'high' : v.flag_rate > 5 ? 'medium' : 'low'}`}>
                      {v.flag_rate.toFixed(1)}%
                    </span>
                  </td>
                  <td>
                    <span style={{ color: getRiskColor(v.avg_risk_score), fontWeight: 600 }}>
                      {v.avg_risk_score.toFixed(1)}
                    </span>
                  </td>
                  <td>${v.total_amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                </tr>
              ))}
              {vendors.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: 'center', padding: '2rem', opacity: 0.5 }}>No vendor data available</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
