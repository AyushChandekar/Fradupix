import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || '';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

// Attach JWT token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('fradupix_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401 responses
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('fradupix_token');
      localStorage.removeItem('fradupix_user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// ──── Auth ────
export const authAPI = {
  login: (email, password) => api.post('/api/auth/login', { email, password }),
  register: (data) => api.post('/api/auth/register', data),
  getProfile: () => api.get('/api/auth/me'),
};

// ──── Invoices (SRS Section 6.1) ────
export const invoiceAPI = {
  upload: (file, onProgress) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/api/v1/invoices/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    });
  },
  batchUpload: (files, onProgress) => {
    const formData = new FormData();
    files.forEach(f => formData.append('files', f));
    return api.post('/api/v1/invoices/upload/batch', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    });
  },
  list: (params) => api.get('/api/v1/invoices', { params }),
  get: (id) => api.get(`/api/v1/invoices/${id}`),
  getEvidence: (id) => api.get(`/api/v1/invoices/${id}/evidence`),
  getHeatmap: (id) => api.get(`/api/v1/invoices/${id}/heatmap`, { responseType: 'blob' }),
  getDuplicates: (id) => api.get(`/api/v1/invoices/${id}/duplicates`),
  review: (id, data) => api.patch(`/api/v1/invoices/${id}/review`, data),
  delete: (id) => api.delete(`/api/v1/invoices/${id}`),
};

// ──── Dashboard & Analytics (SRS Section 6.1) ────
export const dashboardAPI = {
  getStats: (days = 30) => api.get('/api/v1/analytics/dashboard', { params: { days } }),
  getAlerts: (params) => api.get('/api/v1/dashboard/alerts', { params }),
  getRiskDistribution: (days = 30) => api.get('/api/v1/dashboard/risk-distribution', { params: { days } }),
  getTimeline: (days = 30) => api.get('/api/v1/dashboard/timeline', { params: { days } }),
  getVendorAnalytics: (params) => api.get('/api/v1/analytics/vendors', { params }),
};

// ──── Documents / RAG (SRS FR-800) ────
export const documentAPI = {
  query: (data) => api.post('/api/v1/documents/query', data),
  getTOC: (id) => api.get(`/api/v1/documents/${id}/toc`),
};

// ──── Admin (SRS Section 6.1) ────
export const adminAPI = {
  getModelMetrics: () => api.get('/api/v1/admin/models/metrics'),
  retrainModels: () => api.post('/api/v1/admin/models/retrain'),
  getAuditLog: (params) => api.get('/api/v1/audit-log', { params }),
  getWebhooks: () => api.get('/api/v1/admin/webhooks'),
  createWebhook: (data) => api.post('/api/v1/admin/webhooks', data),
  updateRiskWeights: (data) => api.put('/api/v1/admin/risk-weights', data),
  updateRiskThresholds: (data) => api.put('/api/v1/admin/risk-thresholds', data),
};

export default api;
