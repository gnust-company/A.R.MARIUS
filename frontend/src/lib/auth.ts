// Auth token store + the auth endpoints (register/login/refresh).
//
// Kept deliberately free of any dependency on `api.ts` so the request wrapper there can
// import token access + refresh from here without an import cycle. Tokens live in
// localStorage; a `getToken()` reads the current access token for the Bearer header.

import { API_BASE } from './env'

const ACCESS_KEY = 'armarius.access'
const REFRESH_KEY = 'armarius.refresh'

export interface UserDTO {
  id: string
  email: string
  username: string
  full_name: string
  role: string
  is_active: boolean
  is_verified: boolean
  created_at?: string | null
  last_login_at?: string | null
}

interface TokensDTO {
  access_token: string
  refresh_token: string
  token_type?: string
}

interface AuthResultDTO {
  user: UserDTO
  tokens: TokensDTO
}

export function getToken(): string | null {
  return localStorage.getItem(ACCESS_KEY)
}

function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function isAuthenticated(): boolean {
  return getToken() !== null
}

function setTokens(tokens: TokensDTO): void {
  localStorage.setItem(ACCESS_KEY, tokens.access_token)
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token)
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

/** Low-level POST for the unauthenticated auth endpoints (no Bearer, no refresh loop). */
async function authPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : detail
    } catch {
      // non-JSON error body — keep the status line
    }
    throw new Error(detail)
  }
  return (await res.json()) as T
}

export async function login(email: string, password: string): Promise<UserDTO> {
  const result = await authPost<AuthResultDTO>('/auth/login', { email, password })
  setTokens(result.tokens)
  return result.user
}

export async function register(
  email: string,
  fullName: string,
  password: string,
): Promise<UserDTO> {
  const result = await authPost<AuthResultDTO>('/auth/register', {
    email,
    full_name: fullName,
    password,
  })
  setTokens(result.tokens)
  return result.user
}

export function logout(): void {
  clearTokens()
}

/** Refresh the access token once using the stored refresh token. Returns success. */
export async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  try {
    const tokens = await authPost<TokensDTO>('/auth/refresh', { refresh_token: refresh })
    setTokens(tokens)
    return true
  } catch {
    clearTokens()
    return false
  }
}
