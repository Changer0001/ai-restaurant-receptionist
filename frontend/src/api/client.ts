import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from './tokenStorage'

export const apiClient = axios.create({ baseURL: '/api' })

apiClient.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// A 401 on any request (other than the refresh call itself) triggers
// exactly one in-flight token refresh, shared by every request that
// hits it concurrently — without this, several requests failing at
// once (e.g. a page loading three resources in parallel) would each
// fire their own refresh call and race to use a refresh token that the
// first one to finish already rotated/invalidated.
let refreshInFlight: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    throw new Error('No refresh token available')
  }
  const response = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
  const { access_token, refresh_token } = response.data
  setTokens(access_token, refresh_token)
  return access_token
}

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean }

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined
    const isAuthEndpoint = config?.url?.includes('/auth/login') || config?.url?.includes('/auth/refresh')

    if (error.response?.status === 401 && config && !config._retried && !isAuthEndpoint) {
      config._retried = true
      try {
        refreshInFlight ??= refreshAccessToken().finally(() => {
          refreshInFlight = null
        })
        const newAccessToken = await refreshInFlight
        config.headers.Authorization = `Bearer ${newAccessToken}`
        return apiClient(config)
      } catch {
        clearTokens()
        window.location.assign('/login')
        return Promise.reject(error)
      }
    }

    return Promise.reject(error)
  },
)

/** Best-effort human-readable message out of a FastAPI error response. */
export function extractErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0 && typeof detail[0]?.msg === 'string') {
      return detail.map((d) => d.msg).join('; ')
    }
    if (error.message) return error.message
  }
  return 'Something went wrong. Please try again.'
}
