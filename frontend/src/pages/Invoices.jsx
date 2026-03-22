import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Search, Filter, ChevronLeft, ChevronRight, Eye, Trash2, Download
} from 'lucide-react'
import { invoiceAPI } from '../services/api'

const initialInvoices = []

const formatCurrency = (amount, currency = 'USD') =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount || 0)

export default function Invoices() {
  const [invoices, setInvoices] = useState(initialInvoices)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [riskFilter, setRiskFilter] = useState('')
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  useEffect(() => {
    const status = searchParams.get('status')
    if (status) setStatusFilter(status)
  }, [searchParams])

  useEffect(() => {
    const loadInvoices = async () => {
      try {
        const res = await invoiceAPI.list({
          page,
          page_size: 20,
          search: search || undefined,
          status: statusFilter || undefined,
          risk_level: riskFilter || undefined,
        })
        setInvoices(res.data.invoices)
        setTotal(res.data.total)
      } catch (err) {
        console.error("Failed to load invoices:", err)
      }
    }
    loadInvoices()
  }, [page, search, statusFilter, riskFilter])

  return (
    <div>
      <div className="table-container">
        <div className="table-header">
          <div className="table-title">
            All Invoices
            <span style={{ fontSize: 13, color: 'var(--text-tertiary)', fontWeight: 400, marginLeft: 8 }}>
              ({total} records)
            </span>
          </div>
          <div className="table-actions">
            <div className="header-search" style={{ margin: 0 }}>
              <Search className="header-search-icon" size={16} />
              <input
                type="text"
                placeholder="Search invoices..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ width: 220 }}
              />
            </div>
            <select
              className="form-input"
              style={{ width: 140, height: 38, fontSize: 12 }}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">All Status</option>
              <option value="uploaded">Uploaded</option>
              <option value="processing">Processing</option>
              <option value="analyzed">Analyzed</option>
              <option value="flagged">Flagged</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="under_review">Under Review</option>
            </select>
            <select
              className="form-input"
              style={{ width: 140, height: 38, fontSize: 12 }}
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
            >
              <option value="">All Risk</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>
        </div>

        <table>
          <thead>
            <tr>
              <th>Invoice</th>
              <th>Vendor</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Risk Score</th>
              <th>Forgery</th>
              <th>Duplicate</th>
              <th>Anomaly</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv, i) => (
              <tr key={inv.id} className="animate-fade-in" style={{ animationDelay: `${i * 30}ms` }}>
                <td>
                  <div className="table-filename">{inv.filename}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                    {inv.invoice_number || '—'}
                  </div>
                </td>
                <td>{inv.vendor_name || '—'}</td>
                <td className="table-amount">{formatCurrency(inv.total_amount, inv.currency)}</td>
                <td>
                  <span className={`badge-status badge-${inv.status}`}>
                    {inv.status?.replace('_', ' ')}
                  </span>
                </td>
                <td>
                  <div className="risk-meter">
                    <div className="risk-meter-bar">
                      <div
                        className={`risk-meter-fill ${inv.risk_level}`}
                        style={{ width: `${inv.risk_score}%` }}
                      />
                    </div>
                    <span className="risk-meter-value" style={{
                      color: inv.risk_level === 'critical' ? 'var(--critical-500)' :
                             inv.risk_level === 'high' ? 'var(--danger-400)' :
                             inv.risk_level === 'medium' ? 'var(--warning-400)' : 'var(--success-400)'
                    }}>
                      {inv.risk_score}
                    </span>
                  </div>
                </td>
                <td>
                  <span className={`badge ${inv.forgery_score > 50 ? 'badge-high' : inv.forgery_score > 20 ? 'badge-medium' : 'badge-low'}`}>
                    {inv.forgery_score}
                  </span>
                </td>
                <td>
                  <span className={`badge ${inv.duplicate_score > 50 ? 'badge-high' : inv.duplicate_score > 20 ? 'badge-medium' : 'badge-low'}`}>
                    {inv.duplicate_score}
                  </span>
                </td>
                <td>
                  <span className={`badge ${inv.anomaly_score > 50 ? 'badge-high' : inv.anomaly_score > 20 ? 'badge-medium' : 'badge-low'}`}>
                    {inv.anomaly_score}
                  </span>
                </td>
                <td>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button
                      className="btn btn-ghost btn-icon btn-sm"
                      onClick={() => navigate(`/invoices/${inv.id}`)}
                      title="View Details"
                    >
                      <Eye size={16} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {invoices.length === 0 && (
          <div className="empty-state">
            <div className="empty-state-icon"><Search size={32} /></div>
            <h3>No invoices found</h3>
            <p>Try adjusting your search or filter criteria</p>
          </div>
        )}

        <div className="pagination">
          <div className="pagination-info">
            Showing {Math.min((page - 1) * 20 + 1, total)}-{Math.min(page * 20, total)} of {total}
          </div>
          <div className="pagination-controls">
            <button className="pagination-btn" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>
              <ChevronLeft size={16} />
            </button>
            <button className="pagination-btn active">{page}</button>
            <button className="pagination-btn" onClick={() => setPage(p => p + 1)} disabled={page * 20 >= total}>
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
