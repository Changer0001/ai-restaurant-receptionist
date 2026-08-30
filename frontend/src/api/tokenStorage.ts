// Tokens live in localStorage, not an httpOnly cookie: the backend is a
// pure bearer-token JSON API (see backend/app/api/deps.py) that never
// sets cookies, and this is an internal admin dashboard rather than a
// public-facing app handling untrusted third-party content — the usual
// XSS-vs-localStorage tradeoff that argues for httpOnly cookies matters
// less here. Revisit if this dashboard ever embeds untrusted content.

const ACCESS_TOKEN_KEY = 'ai_receptionist_access_token'
const REFRESH_TOKEN_KEY = 'ai_receptionist_refresh_token'

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

export function setTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken)
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}
