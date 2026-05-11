import React, { createContext, useContext, useState, useCallback } from 'react';
import type { Toast } from '@/types';
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react';

interface ToastContextType {
  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { ...toast, id }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ addToast, removeToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-3">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className="animate-slide-in-right flex items-start gap-3 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-custom)] shadow-lg p-4 min-w-[320px] max-w-[400px]"
            style={{
              borderLeftWidth: '4px',
              borderLeftColor:
                toast.type === 'success'
                  ? 'var(--accent-emerald)'
                  : toast.type === 'error'
                  ? 'var(--accent-rose)'
                  : 'var(--accent-blue)',
            }}
          >
            {toast.type === 'success' && (
              <CheckCircle className="w-5 h-5 text-[var(--accent-emerald)] shrink-0 mt-0.5" />
            )}
            {toast.type === 'error' && (
              <AlertCircle className="w-5 h-5 text-[var(--accent-rose)] shrink-0 mt-0.5" />
            )}
            {toast.type === 'info' && (
              <Info className="w-5 h-5 text-[var(--accent-blue)] shrink-0 mt-0.5" />
            )}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-[var(--text-primary)]">{toast.title}</p>
              {toast.message && (
                <p className="text-xs text-[var(--text-secondary)] mt-1">{toast.message}</p>
              )}
            </div>
            <button
              onClick={() => removeToast(toast.id)}
              className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (context === undefined) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}
