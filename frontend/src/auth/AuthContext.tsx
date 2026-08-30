import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import * as authApi from '@/api/auth'
import { clearTokens, getAccessToken, setTokens } from '@/api/tokenStorage'
import type { User } from '@/api/types'

interface AuthContextValue {
  user: User | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (payload: authApi.RegisterPayload) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    async function restoreSession() {
      if (!getAccessToken()) {
        setIsLoading(false)
        return
      }
      try {
        setUser(await authApi.getCurrentUser())
      } catch {
        clearTokens()
      } finally {
        setIsLoading(false)
      }
    }
    void restoreSession()
  }, [])

  async function login(email: string, password: string) {
    const tokens = await authApi.login({ email, password })
    setTokens(tokens.access_token, tokens.refresh_token)
    setUser(await authApi.getCurrentUser())
  }

  async function register(payload: authApi.RegisterPayload) {
    const tokens = await authApi.register(payload)
    setTokens(tokens.access_token, tokens.refresh_token)
    setUser(await authApi.getCurrentUser())
  }

  function logout() {
    clearTokens()
    setUser(null)
  }

  const value = useMemo(() => ({ user, isLoading, login, register, logout }), [user, isLoading])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
