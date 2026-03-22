import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authAPI } from '../services/api'

export default function Login() {
  const [isLogin, setIsLogin] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      let res
      if (isLogin) {
        res = await authAPI.login(email, password)
      } else {
        res = await authAPI.register({ email, username, password, full_name: fullName, role: 'auditor' })
      }

      const { access_token, user } = res.data
      localStorage.setItem('aidetect_token', access_token)
      localStorage.setItem('aidetect_user', JSON.stringify(user))
      navigate('/')
    } catch (err) {
      setError(err.response?.data?.detail || 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  const handleDemoLogin = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      // Use the real backend credentials
      const res = await authAPI.login('admin@aidetect.com', 'admin123')
      const { access_token, user } = res.data
      localStorage.setItem('aidetect_token', access_token)
      localStorage.setItem('aidetect_user', JSON.stringify(user))
      navigate('/')
    } catch (err) {
      setError(err.response?.data?.detail || 'Demo login failed. Make sure backend is running.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-container animate-slide-up">
        <div className="login-brand">
          <div className="login-brand-icon">🛡️</div>
          <h1>AiDetect</h1>
          <p>AI-Powered Invoice Fraud Detection Engine</p>
        </div>

        <form onSubmit={handleSubmit}>
          {!isLogin && (
            <>
              <div className="form-group">
                <label className="form-label">Full Name</label>
                <input
                  className="form-input"
                  type="text"
                  placeholder="Enter your full name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Username</label>
                <input
                  className="form-input"
                  type="text"
                  placeholder="Choose a username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              </div>
            </>
          )}

          <div className="form-group">
            <label className="form-label">Email Address</label>
            <input
              className="form-input"
              type="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">Password</label>
            <input
              className="form-input"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          {error && <div className="form-error" style={{ marginBottom: 16 }}>{error}</div>}

          <button
            className="btn btn-primary login-btn"
            type="submit"
            disabled={loading}
          >
            {loading ? (
              <span className="processing-indicator">
                <span className="spinner" />
                <span>{isLogin ? 'Signing in...' : 'Creating account...'}</span>
              </span>
            ) : (
              isLogin ? 'Sign In' : 'Create Account'
            )}
          </button>
        </form>

        <div style={{ margin: '16px 0', textAlign: 'center', position: 'relative' }}>
          <div style={{
            position: 'absolute', top: '50%', left: 0, right: 0,
            height: 1, background: 'var(--border-subtle)'
          }} />
          <span style={{
            position: 'relative', padding: '0 16px',
            background: 'var(--bg-secondary)', fontSize: 12,
            color: 'var(--text-tertiary)'
          }}>or</span>
        </div>

        <button
          className="btn btn-secondary"
          style={{ width: '100%', height: 48 }}
          onClick={handleDemoLogin}
        >
          🚀 Enter Demo Mode
        </button>

        <div className="login-footer">
          {isLogin ? (
            <>Don't have an account? <a href="#" onClick={(e) => { e.preventDefault(); setIsLogin(false) }}>Register</a></>
          ) : (
            <>Already have an account? <a href="#" onClick={(e) => { e.preventDefault(); setIsLogin(true) }}>Sign In</a></>
          )}
        </div>
      </div>
    </div>
  )
}
