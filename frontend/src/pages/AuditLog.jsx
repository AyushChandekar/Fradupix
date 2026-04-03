import { useState, useEffect } from 'react'
import { adminAPI } from '../services/api'
import { ScrollText, Filter, ChevronLeft, ChevronRight } from 'lucide-react'

export default function AuditLog() {
  const [entries, setEntries] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [actionFilter, setActionFilter] = useState('')

  useEffect(() => {
    setLoading(true)
    const params = { page, page_size: 30 }
    if (actionFilter) params.action = actionFilter
    adminAPI.getAuditLog(params)
      .then(res => {
        setEntries(res.data.entries || [])
        setTotal(res.data.total || 0)
      })
      .catch(() => { setEntries([]); setTotal(0) })
      .finally(() => setLoading(false))
  }, [page, actionFilter])

  const totalPages = Math.ceil(total / 30)

  const actionColors = {
    invoice_uploaded: '#3b82f6',
    invoice_reviewed: '#8b5cf6',
    processing_ocr: '#f59e0b',
    processing_fraud_detection: '#ef4444',
    user_login: '#22c55e',
  }

  return (
    <div className="page-audit-log">
      <div className="page-header">
        <h2><ScrollText size={24} /> Audit Trail</h2>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <Filter size={16} />
          <select value={actionFilter} onChange={e => { setActionFilter(e.target.value); setPage(1) }} className="select-input">
            <option value="">All Actions</option>
            <option value="invoice_uploaded">Invoice Uploaded</option>
            <option value="invoice_reviewed">Invoice Reviewed</option>
            <option value="user_login">User Login</option>
            <option value="processing_ocr">OCR Processing</option>
          </select>
        </div>
      </div>

      <div className="card" style={{ padding: '1.5rem' }}>
        {loading ? (
          <div className="loading">Loading audit log...</div>
        ) : (
          <>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>User ID</th>
                  <th>IP Address</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(entry => (
                  <tr key={entry.id}>
                    <td style={{ whiteSpace: 'nowrap', fontSize: '0.85rem' }}>
                      {new Date(entry.created_at).toLocaleString()}
                    </td>
                    <td>
                      <span style={{
                        padding: '2px 8px', borderRadius: 4, fontSize: '0.8rem', fontWeight: 600,
                        background: (actionColors[entry.action] || '#6b7280') + '20',
                        color: actionColors[entry.action] || '#9ca3af'
                      }}>
                        {entry.action}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.85rem' }}>{entry.entity_type || '-'}</td>
                    <td style={{ fontSize: '0.8rem', fontFamily: 'monospace' }}>
                      {entry.user_id ? entry.user_id.substring(0, 8) + '...' : '-'}
                    </td>
                    <td style={{ fontSize: '0.85rem' }}>{entry.ip_address || '-'}</td>
                    <td style={{ fontSize: '0.8rem', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {entry.details ? JSON.stringify(entry.details).substring(0, 80) : '-'}
                    </td>
                  </tr>
                ))}
                {entries.length === 0 && (
                  <tr><td colSpan={6} style={{ textAlign: 'center', padding: '2rem', opacity: 0.5 }}>No audit entries found</td></tr>
                )}
              </tbody>
            </table>

            {/* Pagination */}
            {totalPages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', gap: '0.5rem', marginTop: '1rem', alignItems: 'center' }}>
                <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                  <ChevronLeft size={16} />
                </button>
                <span style={{ fontSize: '0.85rem' }}>Page {page} of {totalPages} ({total} entries)</span>
                <button className="btn btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                  <ChevronRight size={16} />
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
