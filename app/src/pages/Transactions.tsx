import { useState, useMemo, useEffect } from 'react';
import { useToast } from '@/context/ToastContext';
import { useAuth } from '@/context/AuthContext';
import { vehiclesApi, accountsApi } from '@/services/api';
import type { ApiTransaction } from '@/types';
import {
  Search,
  Download,
  Filter,
  Calendar,
  FileDown,
  Loader2,
  RefreshCw,
} from 'lucide-react';

const TYPE_OPTIONS = ['All', 'toll_deduction', 'topup', 'refund', 'transfer_out', 'transfer_in'];

export default function Transactions() {
  const { addToast } = useToast();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [transactions, setTransactions] = useState<ApiTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('All');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [showFilters, setShowFilters] = useState(false);

  const fetchTransactions = async () => {
    setLoading(true);
    try {
      const allTx: ApiTransaction[] = [];

      if (isAdmin) {
        // Admin: get all accounts then their transactions
        const accounts = await accountsApi.adminAll();
        for (const account of accounts) {
          try {
            const resp = await accountsApi.transactions(account.id);
            allTx.push(...(resp.results || []));
          } catch {
            // skip failed accounts
          }
        }
      } else {
        // User: get their vehicles → accounts → transactions
        const vehicles = await vehiclesApi.list();
        for (const vehicle of vehicles) {
          try {
            const account = await accountsApi.byVehicle(vehicle.id);
            const resp = await accountsApi.transactions(account.id);
            allTx.push(...(resp.results || []));
          } catch {
            // skip vehicles without accounts
          }
        }
      }

      // Sort by date desc
      allTx.sort(
        (a, b) => new Date(b.processed_at).getTime() - new Date(a.processed_at).getTime()
      );
      setTransactions(allTx);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load transactions';
      addToast({ type: 'error', title: 'Error', message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTransactions();
  }, [isAdmin]);

  const filtered = useMemo(() => {
    return transactions.filter((tx) => {
      const s = search.toLowerCase();
      const matchesSearch =
        tx.id.toLowerCase().includes(s) ||
        tx.tag_serial?.toLowerCase().includes(s) ||
        tx.transaction_type.toLowerCase().includes(s) ||
        tx.description?.toLowerCase().includes(s);
      const matchesType = typeFilter === 'All' || tx.transaction_type === typeFilter;
      const txDate = new Date(tx.processed_at);
      const matchesDateFrom = !dateFrom || txDate >= new Date(dateFrom);
      const matchesDateTo = !dateTo || txDate <= new Date(dateTo + 'T23:59:59');
      return matchesSearch && matchesType && matchesDateFrom && matchesDateTo;
    });
  }, [transactions, search, typeFilter, dateFrom, dateTo]);

  const exportCSV = () => {
    const headers = ['Transaction ID', 'Type', 'Amount', 'Balance Before', 'Balance After', 'Status', 'Date'];
    const rows = filtered.map((tx) => [
      tx.id,
      tx.transaction_type,
      tx.amount,
      tx.balance_before,
      tx.balance_after,
      tx.status,
      new Date(tx.processed_at).toLocaleString('en-PK'),
    ]);

    const csv = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `transactions_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);

    addToast({ type: 'success', title: 'Export Complete', message: `${filtered.length} transactions exported to CSV.` });
  };

  const totalAmount = filtered.reduce((sum, tx) => sum + parseFloat(tx.amount || '0'), 0);

  const getTypeColor = (type: string) => {
    switch (type) {
      case 'toll_deduction': return 'bg-[var(--accent-rose)]/10 text-[var(--accent-rose)] border-[var(--accent-rose)]/20';
      case 'topup': return 'bg-[var(--accent-emerald)]/10 text-[var(--accent-emerald)] border-[var(--accent-emerald)]/20';
      case 'refund': return 'bg-[var(--accent-amber)]/10 text-[var(--accent-amber)] border-[var(--accent-amber)]/20';
      case 'transfer_out': return 'bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border-[var(--accent-blue)]/20';
      case 'transfer_in': return 'bg-[var(--accent-cyan)]/10 text-[var(--accent-cyan)] border-[var(--accent-cyan)]/20';
      default: return 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] border-[var(--border-custom)]';
    }
  };

  const getTypeLabel = (type: string) => {
    switch (type) {
      case 'toll_deduction': return 'Toll';
      case 'topup': return 'Top-up';
      case 'refund': return 'Refund';
      case 'transfer_out': return 'Transfer Out';
      case 'transfer_in': return 'Transfer In';
      default: return type;
    }
  };

  return (
    <div className="animate-fade-in-up">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Transaction History</h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            {loading ? 'Loading...' : `${filtered.length} transactions • Total: PKR ${totalAmount.toLocaleString()}`}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={fetchTransactions}
            className="flex items-center gap-2 px-4 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-secondary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors self-start"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
          <button
            onClick={exportCSV}
            disabled={loading || filtered.length === 0}
            className="flex items-center gap-2 px-4 py-2.5 bg-[var(--accent-emerald)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity self-start disabled:opacity-50"
          >
            <Download className="w-4 h-4" />
            Export CSV
          </button>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-4 mb-6 shadow-sm">
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-tertiary)]" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search transactions..."
              className="w-full pl-10 pr-4 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--accent-blue)] focus:ring-2 focus:ring-[var(--accent-blue)]/20 transition-all"
            />
          </div>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`flex items-center gap-2 px-4 py-2.5 border rounded-xl text-sm font-medium transition-colors ${
              showFilters
                ? 'bg-[var(--accent-blue)]/10 border-[var(--accent-blue)]/30 text-[var(--accent-blue)]'
                : 'bg-[var(--bg-elevated)] border-[var(--border-custom)] text-[var(--text-secondary)]'
            }`}
          >
            <Filter className="w-4 h-4" />
            Filters
          </button>
        </div>

        {showFilters && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4 pt-4 border-t border-[var(--border-custom)] animate-fade-in-up">
            <div>
              <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">Type</label>
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="w-full px-3 py-2 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-lg text-sm text-[var(--text-primary)] outline-none"
              >
                {TYPE_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t === 'All' ? 'All Types' : getTypeLabel(t)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">From Date</label>
              <div className="relative">
                <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-tertiary)]" />
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="w-full pl-10 pr-3 py-2 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-lg text-sm text-[var(--text-primary)] outline-none"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">To Date</label>
              <div className="relative">
                <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-tertiary)]" />
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="w-full pl-10 pr-3 py-2 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-lg text-sm text-[var(--text-primary)] outline-none"
                />
              </div>
            </div>
            <div className="flex items-end">
              <button
                onClick={() => {
                  setTypeFilter('All');
                  setDateFrom('');
                  setDateTo('');
                  setSearch('');
                }}
                className="px-3 py-2 text-sm text-[var(--accent-rose)] hover:bg-[var(--accent-rose)]/10 rounded-lg transition-colors"
              >
                Reset All
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-8 h-8 animate-spin text-[var(--accent-blue)]" />
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="bg-[var(--bg-elevated)]">
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">ID</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Type</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Tag Serial</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Date & Time</th>
                  <th className="text-right px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Amount</th>
                  <th className="text-right px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Balance After</th>
                  <th className="text-center px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-12 text-center">
                      <FileDown className="w-10 h-10 text-[var(--text-tertiary)] mx-auto mb-3" />
                      <p className="text-sm text-[var(--text-secondary)]">No transactions found</p>
                      <button
                        onClick={() => {
                          setTypeFilter('All');
                          setDateFrom('');
                          setDateTo('');
                          setSearch('');
                        }}
                        className="text-sm text-[var(--accent-blue)] mt-2 hover:underline"
                      >
                        Clear filters
                      </button>
                    </td>
                  </tr>
                ) : (
                  filtered.map((tx) => (
                    <tr
                      key={tx.id}
                      className="border-b border-[var(--border-custom)] hover:bg-[var(--bg-elevated)] hover:translate-x-1 transition-all duration-200 cursor-pointer"
                    >
                      <td className="px-6 py-4 text-sm font-mono text-[var(--text-primary)]">
                        #{tx.id.slice(0, 8).toUpperCase()}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${getTypeColor(tx.transaction_type)}`}>
                          {getTypeLabel(tx.transaction_type)}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-sm font-mono text-[var(--text-secondary)]">
                        {tx.tag_serial || '—'}
                      </td>
                      <td className="px-6 py-4 text-sm text-[var(--text-secondary)]">
                        {new Date(tx.processed_at).toLocaleDateString('en-PK', {
                          day: 'numeric',
                          month: 'short',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </td>
                      <td className="px-6 py-4 text-sm font-semibold text-right">
                        <span className={
                          tx.transaction_type === 'topup' || tx.transaction_type === 'refund' || tx.transaction_type === 'transfer_in'
                            ? 'text-[var(--accent-emerald)]'
                            : 'text-[var(--accent-rose)]'
                        }>
                          {tx.transaction_type === 'toll_deduction' || tx.transaction_type === 'transfer_out' ? '-' : '+'}PKR {parseFloat(tx.amount).toLocaleString()}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-sm text-[var(--text-primary)] text-right">
                        PKR {parseFloat(tx.balance_after || '0').toLocaleString()}
                      </td>
                      <td className="px-6 py-4 text-center">
                        <span
                          className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${
                            tx.status === 'completed' || tx.status === 'success'
                              ? 'bg-[var(--accent-emerald)]/10 text-[var(--accent-emerald)] border-[var(--accent-emerald)]/20'
                              : tx.status === 'failed'
                              ? 'bg-[var(--accent-rose)]/10 text-[var(--accent-rose)] border-[var(--accent-rose)]/20'
                              : 'bg-[var(--accent-amber)]/10 text-[var(--accent-amber)] border-[var(--accent-amber)]/20'
                          }`}
                        >
                          {tx.status}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
