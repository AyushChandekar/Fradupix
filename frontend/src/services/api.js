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

// ──── Invoices ────
export const invoiceAPI = {
  upload: (file, onProgress) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/api/invoices/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    });
  },
  list: (params) => api.get('/api/invoices', { params }),
  get: (id) => api.get(`/api/invoices/${id}`),
  getEvidence: (id) => api.get(`/api/invoices/${id}/evidence`),
  review: (id, data) => api.post(`/api/invoices/${id}/review`, data),
  delete: (id) => api.delete(`/api/invoices/${id}`),
};

// ──── Dashboard ────
export const dashboardAPI = {
  getStats: (days = 30) => api.get('/api/dashboard/stats', { params: { days } }),
  getAlerts: (params) => api.get('/api/dashboard/alerts', { params }),
  getRiskDistribution: (days = 30) => api.get('/api/dashboard/risk-distribution', { params: { days } }),
  getTimeline: (days = 30) => api.get('/api/dashboard/timeline', { params: { days } }),
};

export default api;
