import axios from 'axios';
import { API_BASE_URL } from '../utils/constants';
import { attachParsedApiError } from './error';
import { dispatchLoginRequired, isGuestSessionActive } from '../utils/guestAccess';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const path = window.location.pathname + window.location.search;
      if (isGuestSessionActive()) {
        const method = String(error.config?.method || 'get').toUpperCase();
        const isRead = ['GET', 'HEAD', 'OPTIONS'].includes(method);
        dispatchLoginRequired(isRead
          ? '该内容属于个人账号数据，需要先登录后查看。'
          : '该操作会创建或修改个人数据，需要先登录账号。');
      } else if (!path.startsWith('/login')) {
        const redirect = encodeURIComponent(path);
        window.location.assign(`/login?redirect=${redirect}`);
      }
    }
    attachParsedApiError(error);
    return Promise.reject(error);
  }
);

export default apiClient;
