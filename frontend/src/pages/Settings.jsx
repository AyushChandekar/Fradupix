import { useState, useEffect } from 'react'
import { adminAPI } from '../services/api'
import { Wrench, Save, RefreshCw, Activity, Webhook } from 'lucide-react'

export default function Settings() {
  const [weights, setWeights] = useState({ forgery_weight: 0.30, duplicate_weight: 0.25, anomaly_weight: 0.25, rules_weight: 0.20 })
  const [thresholds, setThresholds] = useState({ low_max: 30, medium_max: 60, high_max: 85 })
  const [metrics, setMetrics] = useState(null)
  const [retrainStatus, setRetrainStatus] = useState('')
  const [saveStatus, setSaveStatus] = useState('')

  useEffect(() => {
    adminAPI.getModelMetrics()
      .then(res => setMetrics(res.data))
      .catch(() => {})
  }, [])

  const saveWeights = () => {
    setSaveStatus('saving')
    adminAPI.updateRiskWeights(weights)
      .then(() => setSaveStatus('saved'))
      .catch(() => setSaveStatus('error'))
      .finally(() => setTimeout(() => setSaveStatus(''), 2000))
  }

  const saveThresholds = () => {
    setSaveStatus('saving')
    adminAPI.updateRiskThresholds(thresholds)
      .then(() => setSaveStatus('saved'))
      .catch(() => setSaveStatus('error'))
      .finally(() => setTimeout(() => setSaveStatus(''), 2000))
  }

  const handleRetrain = () => {
    setRetrainStatus('training')
    adminAPI.retrainModels()
      .then(res => setRetrainStatus(res.data.status || 'done'))
      .catch(() => setRetrainStatus('error'))
      .finally(() => setTimeout(() => setRetrainStatus(''), 3000))
  }

  return (
    <div className="page-settings">
      <div className="page-header">
        <h2><Wrench size={24} /> System Settings</h2>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        {/* Risk Weights (FR-706) */}
        <div className="card" style={{ padding: '1.5rem' }}>
          <h3 style={{ marginBottom: '1rem' }}>Risk Score Weights</h3>
          <p style={{ fontSize: '0.85rem', opacity: 0.6, marginBottom: '1rem' }}>
            Composite = Forgery x W1 + Duplicate x W2 + Anomaly x W3 + Rules x W4
          </p>
          {Object.entries(weights).map(([key, val]) => (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.75rem' }}>
              <label style={{ width: 160, fontSize: '0.9rem', textTransform: 'capitalize' }}>
                {key.replace('_weight', '')}
              </label>
              <input
                type="range" min="0" max="1" step="0.05" value={val}
                onChange={e => setWeights(w => ({ ...w, [key]: parseFloat(e.target.value) }))}
                style={{ flex: 1 }}
              />
              <span style={{ width: 40, textAlign: 'right', fontWeight: 600 }}>{(val * 100).toFixed(0)}%</span>
            </div>
          ))}
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '1rem' }}>
            <span style={{ fontSize: '0.8rem', opacity: 0.5 }}>
              Sum: {(Object.values(weights).reduce((a, b) => a + b, 0) * 100).toFixed(0)}%
            </span>
            <button className="btn btn-primary btn-sm" onClick={saveWeights}>
              <Save size={14} /> Save Weights
            </button>
          </div>
        </div>

        {/* Risk Thresholds (FR-702) */}
        <div className="card" style={{ padding: '1.5rem' }}>
          <h3 style={{ marginBottom: '1rem' }}>Risk Classification Thresholds</h3>
          <p style={{ fontSize: '0.85rem', opacity: 0.6, marginBottom: '1rem' }}>
            Score ranges for Low / Medium / High / Critical classification
          </p>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.75rem' }}>
            <label style={{ width: 120, fontSize: '0.9rem' }}>Low (0 -</label>
            <input type="number" className="input-field" value={thresholds.low_max}
              onChange={e => setThresholds(t => ({ ...t, low_max: parseInt(e.target.value) }))}
              style={{ width: 80 }} />
            <span>)</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.75rem' }}>
            <label style={{ width: 120, fontSize: '0.9rem' }}>Medium (... -</label>
            <input type="number" className="input-field" value={thresholds.medium_max}
              onChange={e => setThresholds(t => ({ ...t, medium_max: parseInt(e.target.value) }))}
              style={{ width: 80 }} />
            <span>)</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.75rem' }}>
            <label style={{ width: 120, fontSize: '0.9rem' }}>High (... -</label>
            <input type="number" className="input-field" value={thresholds.high_max}
              onChange={e => setThresholds(t => ({ ...t, high_max: parseInt(e.target.value) }))}
              style={{ width: 80 }} />
            <span>)</span>
          </div>
          <div style={{ fontSize: '0.85rem', opacity: 0.6, marginBottom: '1rem' }}>
            Critical: {thresholds.high_max + 1} - 100
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button className="btn btn-primary btn-sm" onClick={saveThresholds}>
              <Save size={14} /> Save Thresholds
            </button>
          </div>
          {saveStatus && (
            <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: saveStatus === 'saved' ? '#22c55e' : saveStatus === 'error' ? '#ef4444' : '#f59e0b' }}>
              {saveStatus === 'saved' ? 'Saved successfully' : saveStatus === 'error' ? 'Save failed' : 'Saving...'}
            </div>
          )}
        </div>

        {/* ML Model Management (FR-606) */}
        <div className="card" style={{ padding: '1.5rem' }}>
          <h3 style={{ marginBottom: '1rem' }}><Activity size={18} /> ML Model Metrics</h3>
          {metrics ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              <div><span style={{ opacity: 0.6 }}>Model:</span> <strong>{metrics.model_name}</strong></div>
              <div><span style={{ opacity: 0.6 }}>Samples:</span> <strong>{metrics.training_samples}</strong></div>
              <div><span style={{ opacity: 0.6 }}>Precision:</span> <strong>{(metrics.precision * 100).toFixed(1)}%</strong></div>
              <div><span style={{ opacity: 0.6 }}>Recall:</span> <strong>{(metrics.recall * 100).toFixed(1)}%</strong></div>
              <div><span style={{ opacity: 0.6 }}>F1 Score:</span> <strong>{(metrics.f1_score * 100).toFixed(1)}%</strong></div>
              <div><span style={{ opacity: 0.6 }}>AUC-ROC:</span> <strong>{(metrics.auc_roc * 100).toFixed(1)}%</strong></div>
            </div>
          ) : (
            <p style={{ opacity: 0.5 }}>Unable to load model metrics (Admin access required)</p>
          )}
          <div style={{ marginTop: '1rem' }}>
            <button className="btn btn-secondary btn-sm" onClick={handleRetrain} disabled={retrainStatus === 'training'}>
              <RefreshCw size={14} className={retrainStatus === 'training' ? 'spin' : ''} />
              {retrainStatus === 'training' ? 'Retraining...' : 'Retrain Models'}
            </button>
            {retrainStatus && retrainStatus !== 'training' && (
              <span style={{ marginLeft: '0.5rem', fontSize: '0.85rem', color: retrainStatus === 'error' ? '#ef4444' : '#22c55e' }}>
                {retrainStatus === 'error' ? 'Retraining failed' : `Status: ${retrainStatus}`}
              </span>
            )}
          </div>
        </div>

        {/* Webhook Configuration */}
        <div className="card" style={{ padding: '1.5rem' }}>
          <h3 style={{ marginBottom: '1rem' }}><Webhook size={18} /> Webhook Events</h3>
          <p style={{ fontSize: '0.85rem', opacity: 0.6, marginBottom: '1rem' }}>
            Configure webhook endpoints for external system integration.
          </p>
          <div style={{ fontSize: '0.85rem' }}>
            <div style={{ marginBottom: '0.5rem' }}><strong>Available Events:</strong></div>
            <ul style={{ paddingLeft: '1.25rem', opacity: 0.7 }}>
              <li>invoice.processed - Analysis complete</li>
              <li>invoice.flagged - High/Critical risk</li>
              <li>invoice.approved / invoice.rejected - Audit decision</li>
              <li>model.retrained - ML model updated</li>
              <li>system.alert - System health issues</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
