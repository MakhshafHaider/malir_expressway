import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useAuth } from '@/context/AuthContext';
import { useToast } from '@/context/ToastContext';
import { Eye, EyeOff, Loader2, Phone } from 'lucide-react';

export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const { addToast } = useToast();
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!phone || !password) {
      setError('Please fill in all fields');
      return;
    }
    if (!/^03\d{9}$/.test(phone.replace(/\s/g, ''))) {
      setError('Please enter a valid Pakistani phone number (03XXXXXXXXX)');
      return;
    }

    setIsLoading(true);
    const success = await login(phone.replace(/\s/g, ''), password);
    setIsLoading(false);

    if (success) {
      addToast({ type: 'success', title: 'Welcome back!', message: 'You have successfully signed in.' });
      navigate('/dashboard');
    } else {
      setError('Invalid phone number or password. Please try again.');
      addToast({ type: 'error', title: 'Authentication failed', message: 'Invalid credentials.' });
    }
  };

  return (
    <div className="min-h-screen bg-[var(--bg-body)] flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <img src="/logo.png" alt="Logo" className="w-20 h-20 mb-4" />
          <h1 className="text-2xl font-bold text-[var(--text-primary)] text-center">
            Smart Expressway
          </h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">Toll Management System</p>
        </div>

        {/* Login Card */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-2xl shadow-xl p-8">
          <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-1">Sign In</h2>
          <p className="text-sm text-[var(--text-secondary)] mb-6">
            Enter your credentials to access the dashboard
          </p>

          {error && (
            <div className="mb-4 p-3 rounded-lg bg-[var(--accent-rose)]/10 border border-[var(--accent-rose)]/20 text-sm text-[var(--accent-rose)]">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                Phone Number
              </label>
              <div className="relative">
                <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-tertiary)]" />
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="03001234567"
                  className="w-full pl-10 pr-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--accent-blue)] focus:ring-2 focus:ring-[var(--accent-blue)]/20 transition-all"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                Password
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  className="w-full px-4 py-3 pr-12 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--accent-blue)] focus:ring-2 focus:ring-[var(--accent-blue)]/20 transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
                >
                  {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full flex items-center justify-center gap-2 py-3 bg-gradient-to-r from-[var(--accent-blue)] to-[#6366F1] text-white font-semibold rounded-xl hover:opacity-90 transition-opacity disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Signing in...
                </>
              ) : (
                'Sign In'
              )}
            </button>
          </form>

          <div className="mt-6 pt-4 border-t border-[var(--border-custom)] text-center">
            <p className="text-xs text-[var(--text-secondary)]">
              Government of Pakistan - National Highway Authority
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
