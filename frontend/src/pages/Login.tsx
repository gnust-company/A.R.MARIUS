// Authentication page (Sprint 6). Real JWT login/register against `/auth/*`.
// The `RequireAuth` wrapper redirects any unauthenticated visit to `/login`.

import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { login, register } from '@/lib/auth'
import { useAppStore } from '@/store/appStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'

export default function Login() {
  const navigate = useNavigate()
  const setCurrentUser = useAppStore((s) => s.setCurrentUser)
  const hydrateWorkspaces = useAppStore((s) => s.hydrateWorkspaces)

  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    // Register: require the two password entries to match before hitting the API.
    if (mode === 'register' && password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    setBusy(true)
    try {
      const user =
        mode === 'login'
          ? await login(email.trim(), password)
          : await register(email.trim(), fullName.trim(), password)
      setCurrentUser({ id: user.id, name: user.full_name, email: user.email })
      await hydrateWorkspaces()
      navigate('/workspaces')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="min-h-[100dvh] flex items-center justify-center p-6 bg-[#1a1410]">
      <Card className="w-full max-w-sm bg-[#221a14] border-[#3a2e22] text-[#E8C96A]">
        <CardHeader className="space-y-2 text-center">
          <CardTitle
            className="text-gold"
            style={{ fontFamily: "'Cinzel Decorative', 'Cinzel', serif", letterSpacing: '0.04em' }}
          >
            Armarius
          </CardTitle>
          <CardDescription className="text-[#A89880]">
            {mode === 'login' ? 'Enter the Scriptorium' : 'Claim your seat'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            {mode === 'register' && (
              <div className="space-y-1.5">
                <Label htmlFor="fullName" className="text-[#A89880]">Full name</Label>
                <Input
                  id="fullName"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                  className="bg-[#1a1410] border-[#3a2e22] text-white"
                />
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="email" className="text-[#A89880]">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="bg-[#1a1410] border-[#3a2e22] text-white"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password" className="text-[#A89880]">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                className="bg-[#1a1410] border-[#3a2e22] text-white"
              />
            </div>
            {mode === 'register' && (
              <div className="space-y-1.5">
                <Label htmlFor="confirmPassword" className="text-[#A89880]">Confirm password</Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  minLength={8}
                  className="bg-[#1a1410] border-[#3a2e22] text-white"
                />
              </div>
            )}

            {error && (
              <p className="text-sm text-red-400" role="alert">{error}</p>
            )}

            <Button
              type="submit"
              disabled={busy}
              className="w-full bg-terracotta hover:bg-terracotta-light text-white"
            >
              {busy ? '…' : mode === 'login' ? 'Sign in' : 'Create account'}
            </Button>
          </form>

          <button
            type="button"
            onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null); setConfirmPassword('') }}
            className="mt-4 w-full text-center text-sm text-[#A89880] hover:text-gold transition-colors"
          >
            {mode === 'login' ? 'No account? Register' : 'Already have an account? Sign in'}
          </button>
        </CardContent>
      </Card>
    </main>
  )
}
