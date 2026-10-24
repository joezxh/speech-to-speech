import { api } from './client'
import type { TokenBundle, UserProfile } from '@/types/api'

export const login = (username: string, password: string): Promise<TokenBundle> =>
  api.post<TokenBundle>('/auth/login', { username, password })

export const me = (): Promise<UserProfile> => api.get<UserProfile>('/auth/me')
