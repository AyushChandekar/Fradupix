import { useState, useCallback } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import Dashboard from './pages/Dashboard'
import Invoices from './pages/Invoices'
import Upload from './pages/Upload'
import InvoiceDetail from './pages/InvoiceDetail'
import Alerts from './pages/Alerts'
import Login from './pages/Login'

function getUser() {
  try {
    const u = localStorage.getItem('aidetect_user')
    return u ? JSON.parse(u) : null
  } catch { return null }
}

function ProtectedRoute({ children }) {
  const token = localStorage.getItem('aidetect_token')
  if (!token) return <Navigate to="/login" replace />
  return children
}

function AppLayout({ children, currentPage, onNavigate }) {
  const user = getUser()
  return (
    <div className="app-layout">
      <Sidebar currentPage={currentPage} onNavigate={onNavigate} />
      <div className="main-content">
        <Header user={user} currentPage={currentPage} />
        <div className="page-content">
          {children}
        </div>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={
          <ProtectedRoute>
            <AppLayout currentPage="dashboard">
              <Dashboard />
            </AppLayout>
          </ProtectedRoute>
        } />
        <Route path="/invoices" element={
          <ProtectedRoute>
            <AppLayout currentPage="invoices">
              <Invoices />
            </AppLayout>
          </ProtectedRoute>
        } />
        <Route path="/upload" element={
          <ProtectedRoute>
            <AppLayout currentPage="upload">
              <Upload />
            </AppLayout>
          </ProtectedRoute>
        } />
        <Route path="/invoices/:id" element={
          <ProtectedRoute>
            <AppLayout currentPage="invoices">
              <InvoiceDetail />
            </AppLayout>
          </ProtectedRoute>
        } />
        <Route path="/alerts" element={
          <ProtectedRoute>
            <AppLayout currentPage="alerts">
              <Alerts />
            </AppLayout>
          </ProtectedRoute>
        } />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
