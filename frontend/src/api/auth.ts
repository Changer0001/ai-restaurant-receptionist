import { apiClient } from './client'
import type { TokenResponse, User } from './types'

export interface RegisterPayload {
  email: string
  password: string
  first_name?: string
  last_name?: string
  restaurant_name: string
  restaurant_timezone: string
}

export interface LoginPayload {
  email: string
  password: string
}

export async function register(payload: RegisterPayload): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/auth/register', payload)
  return data
}

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/auth/login', payload)
  return data
}

export async function getCurrentUser(): Promise<User> {
  const { data } = await apiClient.get<User>('/auth/me')
  return data
}
