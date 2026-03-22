import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Upload as UploadIcon, CheckCircle, AlertTriangle, X, FileText } from 'lucide-react'
import { invoiceAPI } from '../services/api'

const ACCEPTED = { 'image/png':1, 'image/jpeg':1, 'image/tiff':1, 'application/pdf':1 }
const fmtSize = (b) => b < 1024 ? `${b} B` : b < 1048576 ? `${(b/1024).toFixed(1)} KB` : `${(b/1048576).toFixed(1)} MB`

export default function Upload() {
  const [files, setFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const navigate = useNavigate()

  const addFiles = (list) => {
    const items = Array.from(list).map(f => ({
      file: f, name: f.name, size: f.size, type: f.type,
      status: ACCEPTED[f.type] ? 'ready' : 'error',
      error: ACCEPTED[f.type] ? null : 'Unsupported type',
      progress: 0, result: null,
    }))
    setFiles(p => [...p, ...items])
  }

  const handleDrag = useCallback(e => {
    e.preventDefault(); e.stopPropagation()
    setDragActive(e.type === 'dragenter' || e.type === 'dragover')
  }, [])

  const handleDrop = useCallback(e => {
    e.preventDefault(); e.stopPropagation(); setDragActive(false)
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files)
  }, [])

  const uploadAll = async () => {
    setUploading(true)
    const u = [...files]
    for (let i = 0; i < u.length; i++) {
      if (u[i].status !== 'ready') continue
      u[i].status = 'uploading'; setFiles([...u])
      try {
        const res = await invoiceAPI.upload(u[i].file, (ev) => {
          u[i].progress = Math.round((ev.loaded * 100) / ev.total); setFiles([...u])
        })
        u[i].status = 'success'; u[i].result = res.data
      } catch (err) {
        u[i].status = 'error'; u[i].error = err.response?.data?.detail || 'Upload failed'
      }
      setFiles([...u])
    }
    setUploading(false)
  }

  const ready = files.filter(f => f.status === 'ready').length
  const done = files.filter(f => f.status === 'success').length

  return (
    <div>
      <div className={`upload-zone ${dragActive ? 'active' : ''}`}
        onDragEnter={handleDrag} onDragLeave={handleDrag} onDragOver={handleDrag} onDrop={handleDrop}
        onClick={() => document.getElementById('fi').click()}>
        <input id="fi" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.tiff" onChange={e => e.target.files?.length && addFiles(e.target.files)} style={{display:'none'}} />
        <div className="upload-icon"><UploadIcon size={32} /></div>
        <div className="upload-title">{dragActive ? 'Drop files here' : 'Drag & drop invoices or click to browse'}</div>
        <div className="upload-subtitle">Upload invoices for AI-powered fraud analysis</div>
        <div className="upload-formats">
          {['PDF','PNG','JPEG','TIFF'].map(f => <span key={f} className="upload-format-tag">{f}</span>)}
        </div>
      </div>

      {files.length > 0 && (
        <div className="card" style={{marginTop:24}}>
          <div className="card-header">
            <div className="card-title">Upload Queue ({files.length})</div>
            <div style={{display:'flex',gap:8}}>
              {done > 0 && <button className="btn btn-secondary btn-sm" onClick={() => navigate('/invoices')}>View Invoices</button>}
              {ready > 0 && <button className="btn btn-primary btn-sm" onClick={uploadAll} disabled={uploading}>
                {uploading ? <><span className="spinner"/> Uploading...</> : <><UploadIcon size={14}/> Upload {ready}</>}
              </button>}
            </div>
          </div>
          {files.map((f, i) => (
            <div key={i} className="animate-slide-up" style={{display:'flex',alignItems:'center',gap:14,padding:'12px 16px',background:'var(--surface-1)',border:'1px solid var(--border-subtle)',borderRadius:'var(--radius-md)',marginBottom:8,animationDelay:`${i*50}ms`}}>
              <div style={{width:40,height:40,borderRadius:'var(--radius-sm)',background:f.status==='success'?'rgba(16,185,129,.15)':f.status==='error'?'rgba(244,63,94,.15)':'rgba(99,102,241,.15)',display:'flex',alignItems:'center',justifyContent:'center',color:f.status==='success'?'var(--success-400)':f.status==='error'?'var(--danger-400)':'var(--primary-400)',flexShrink:0}}>
                {f.status==='success'?<CheckCircle size={20}/>:f.status==='error'?<AlertTriangle size={20}/>:<FileText size={20}/>}
              </div>
              <div style={{flex:1,minWidth:0}}>
                <div style={{fontSize:13,fontWeight:500}}>{f.name}</div>
                <div style={{fontSize:11,color:'var(--text-tertiary)'}}>
                  {fmtSize(f.size)}
                  {f.error && <span style={{color:'var(--danger-400)',marginLeft:8}}>{f.error}</span>}
                  {f.result && <span style={{color:'var(--success-400)',marginLeft:8}}>✓ Queued for analysis</span>}
                </div>
                {f.status==='uploading' && <div style={{marginTop:6,height:4,background:'var(--neutral-800)',borderRadius:999,overflow:'hidden'}}><div style={{height:'100%',width:`${f.progress}%`,background:'var(--gradient-primary)',borderRadius:999,transition:'width .3s'}}/></div>}
              </div>
              {(f.status==='ready'||f.status==='error') && <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setFiles(p => p.filter((_,j) => j!==i))}><X size={16}/></button>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
