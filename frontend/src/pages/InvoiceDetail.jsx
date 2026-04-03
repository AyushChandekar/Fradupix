import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Shield, Copy, AlertTriangle, CheckCircle, XCircle } from 'lucide-react'
import { invoiceAPI } from '../services/api'

const demo = {
  id:'1', filename:'INV-2024-3892.pdf', vendor_name:'Acme Corp', invoice_number:'INV-3892',
  total_amount:15420, currency:'USD', tax_amount:1234, subtotal:14186, buyer_name:'TechCorp Inc',
  status:'flagged', risk_score:94, risk_level:'critical', forgery_score:88, duplicate_score:12, anomaly_score:45,
  ocr_confidence:92, invoice_date:'2024-03-15T00:00:00', created_at:new Date().toISOString(),
  fraud_evidence: {
    forgery:{score:88,summary:'High probability of digital forgery. ELA found 3 suspicious regions.',ela_score:72,suspicious_regions:[{x:120,y:340,width:64,height:64},{x:280,y:340,width:64,height:64},{x:120,y:420,width:64,height:64}]},
    anomaly:{score:45,is_anomalous:false,feature_importance:{total_amount:'high_value'}},
    duplicate:{score:12,is_duplicate:false,summary:'No significant duplicates found'},
    risk_breakdown:{forgery:{score:88,weight:0.3,contribution:26.4},duplicate:{score:12,weight:0.25,contribution:3},anomaly:{score:45,weight:0.25,contribution:11.25},ocr_confidence:{score:8,weight:0.1,contribution:0.8},metadata:{score:40,weight:0.1,contribution:4}},
    recommended_action:'block_and_alert', dominant_risk:'forgery'
  }
}

function ScoreCircle({ score, size=80, color }) {
  const r = (size-12)/2, c = 2*Math.PI*r, offset = c*(1-score/100)
  const col = color || (score>80?'var(--critical-500)':score>60?'var(--danger-400)':score>30?'var(--warning-400)':'var(--success-400)')
  return (
    <div className="score-circle" style={{width:size,height:size}}>
      <svg width={size} height={size}><circle className="score-circle-bg" cx={size/2} cy={size/2} r={r}/><circle className="score-circle-fill" cx={size/2} cy={size/2} r={r} stroke={col} strokeDasharray={c} strokeDashoffset={offset}/></svg>
      <div className="score-circle-value" style={{color:col}}>{score}</div>
    </div>
  )
}

function getUserRole() {
  try {
    const u = localStorage.getItem('fradupix_user')
    return u ? JSON.parse(u).role : null
  } catch { return null }
}

export default function InvoiceDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [inv, setInv] = useState(demo)
  const [decision, setDecision] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const userRole = getUserRole() || 'viewer'
  const canReview = ['admin', 'manager', 'auditor'].includes(userRole)

  useEffect(() => {
    invoiceAPI.get(id).then(r => setInv(r.data)).catch(() => {})
  }, [id])

  const submitReview = async (dec) => {
    setSubmitting(true)
    try { await invoiceAPI.review(id, {decision:dec,notes}); setInv(p=>({...p,status:dec==='approved'?'approved':'rejected'})) }
    catch(e) { setInv(p=>({...p,status:dec==='approved'?'approved':'rejected'})) }
    setSubmitting(false)
  }

  const ev = inv.fraud_evidence || {}
  const bd = ev.risk_breakdown || {}
  const fmt = n => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n||0)

  return (
    <div>
      <button className="btn btn-ghost btn-sm" onClick={() => nav('/invoices')} style={{marginBottom:16}}>
        <ArrowLeft size={16}/> Back to Invoices
      </button>

      {/* Header */}
      <div className="card" style={{marginBottom:16}}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start'}}>
          <div>
            <h2 style={{fontSize:20,fontWeight:700,marginBottom:4}}>{inv.filename}</h2>
            <div style={{fontSize:13,color:'var(--text-tertiary)'}}>Invoice #{inv.invoice_number} • {inv.vendor_name} → {inv.buyer_name}</div>
            <div style={{display:'flex',gap:8,marginTop:12}}>
              <span className={`badge-status badge-${inv.status}`}>{inv.status?.replace('_',' ')}</span>
              <span className={`badge badge-${inv.risk_level}`}>{inv.risk_level?.toUpperCase()}</span>
            </div>
          </div>
          <div style={{textAlign:'center'}}>
            <ScoreCircle score={inv.risk_score} size={90}/>
            <div style={{fontSize:12,color:'var(--text-tertiary)',marginTop:4}}>Risk Score</div>
          </div>
        </div>
      </div>

      {/* Details Grid */}
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:16,marginBottom:16}}>
        <div className="card"><div className="card-title" style={{marginBottom:12}}>Invoice Data</div>
          {[['Amount',fmt(inv.total_amount)],['Subtotal',fmt(inv.subtotal)],['Tax',fmt(inv.tax_amount)],['Currency',inv.currency],['Date',inv.invoice_date?.split('T')[0]],['OCR Confidence',`${inv.ocr_confidence}%`]].map(([k,v])=>(
            <div key={k} style={{display:'flex',justifyContent:'space-between',padding:'6px 0',borderBottom:'1px solid var(--border-subtle)',fontSize:13}}>
              <span style={{color:'var(--text-tertiary)'}}>{k}</span><span style={{fontWeight:600}}>{v||'—'}</span>
            </div>
          ))}
        </div>
        <div className="evidence-card"><div className="evidence-card-header"><Shield size={18} color="var(--primary-400)"/><div className="evidence-card-title">Forgery Analysis</div></div>
          <ScoreCircle score={inv.forgery_score} color="var(--danger-400)"/>
          <p style={{fontSize:12,color:'var(--text-secondary)',textAlign:'center',marginTop:8}}>{ev.forgery?.summary||'No analysis'}</p>
        </div>
        <div className="evidence-card"><div className="evidence-card-header"><Copy size={18} color="var(--accent-400)"/><div className="evidence-card-title">Duplicate Check</div></div>
          <ScoreCircle score={inv.duplicate_score} color="var(--accent-500)"/>
          <p style={{fontSize:12,color:'var(--text-secondary)',textAlign:'center',marginTop:8}}>{ev.duplicate?.summary||'No analysis'}</p>
        </div>
      </div>

      {/* Risk Breakdown */}
      <div className="card" style={{marginBottom:16}}>
        <div className="card-title" style={{marginBottom:16}}>Risk Score Breakdown</div>
        <div style={{display:'flex',flexDirection:'column',gap:12}}>
          {Object.entries(bd).map(([k,v])=>(
            <div key={k} style={{display:'flex',alignItems:'center',gap:16}}>
              <span style={{width:120,fontSize:12,color:'var(--text-tertiary)',textTransform:'capitalize'}}>{k.replace('_',' ')}</span>
              <div style={{flex:1,height:8,background:'var(--neutral-800)',borderRadius:999,overflow:'hidden'}}>
                <div style={{height:'100%',width:`${v.score}%`,background:v.score>60?'var(--danger-400)':v.score>30?'var(--warning-400)':'var(--success-400)',borderRadius:999,transition:'width .5s'}}/>
              </div>
              <span style={{width:40,fontSize:13,fontWeight:700,textAlign:'right'}}>{v.score}</span>
              <span style={{width:50,fontSize:11,color:'var(--text-tertiary)'}}>×{v.weight}</span>
              <span style={{width:50,fontSize:13,fontWeight:600,textAlign:'right',color:'var(--primary-400)'}}>{v.contribution?.toFixed(1)}</span>
            </div>
          ))}
        </div>
        {ev.recommended_action && <div style={{marginTop:16,padding:'12px 16px',background:ev.recommended_action==='block_and_alert'?'rgba(220,38,38,.1)':'rgba(245,158,11,.1)',borderRadius:'var(--radius-md)',fontSize:13,fontWeight:600,color:ev.recommended_action==='block_and_alert'?'var(--critical-500)':'var(--warning-400)'}}>
          Recommended: {ev.recommended_action.replace(/_/g,' ').toUpperCase()}
        </div>}
      </div>

      {/* Review Panel - only shown to admin, manager, auditor */}
      {canReview && inv.status !== 'approved' && inv.status !== 'rejected' && (
        <div className="card">
          <div className="card-title" style={{marginBottom:16}}>Audit Review</div>
          <div className="form-group">
            <label className="form-label">Review Notes</label>
            <textarea className="form-input" style={{height:80,padding:12,resize:'vertical'}} placeholder="Add review notes..." value={notes} onChange={e=>setNotes(e.target.value)}/>
          </div>
          <div style={{display:'flex',gap:12}}>
            <button className="btn btn-success" onClick={() => submitReview('approved')} disabled={submitting}><CheckCircle size={16}/> Approve</button>
            <button className="btn btn-danger" onClick={() => submitReview('rejected')} disabled={submitting}><XCircle size={16}/> Reject</button>
            <button className="btn btn-secondary" onClick={() => submitReview('escalated')} disabled={submitting}><AlertTriangle size={16}/> Escalate</button>
          </div>
        </div>
      )}
    </div>
  )
}
