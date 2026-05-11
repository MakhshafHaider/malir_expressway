import { useState, useEffect, useMemo } from 'react';
import { tollsApi, vehiclesApi } from '@/services/api';
import type { TollTrip, ApiVehicle } from '@/types';
import { useToast } from '@/context/ToastContext';
import { useAuth } from '@/context/AuthContext';
import {
  Route,
  Search,
  Filter,
  Loader2,
  RefreshCw,
  Calendar,
  XCircle,
  RotateCcw,
} from 'lucide-react';

const STATUS_OPTIONS = ['All', 'active', 'completed', 'failed'];

const statusBadge = (status: string) => {
  switch (status) {
    case 'active':
      return 'bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border-[var(--accent-blue)]/20';
    case 'completed':
      return 'bg-[var(--accent-emerald)]/10 text-[var(--accent-emerald)] border-[var(--accent-emerald)]/20';
    case 'failed':
      return 'bg-[var(--accent-rose)]/10 text-[var(--accent-rose)] border-[var(--accent-rose)]/20';
    default:
      return 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] border-[var(--border-custom)]';
  }
};

function formatDuration(minutes?: number): string {
  if (!minutes) return '—';
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}h ${m}m`;
}

const PAGE_SIZE = 15;

export default function TripsPage() {
  const { addToast } = useToast();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [trips, setTrips] = useState<TollTrip[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('All');
  const [search, setSearch] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [closingTripId, setClosingTripId] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState<TollTrip | null>(null);
  const [refundTarget, setRefundTarget] = useState<TollTrip | null>(null);
  const [isRefunding, setIsRefunding] = useState(false);
  const [refundedTripIds, setRefundedTripIds] = useState<Set<string>>(new Set());

  // For non-admin: vehicle selector
  const [vehicles, setVehicles] = useState<ApiVehicle[]>([]);
  const [selectedVehicle, setSelectedVehicle] = useState('');

  useEffect(() => {
    if (!isAdmin) {
      vehiclesApi
        .list()
        .then((data) => {
          setVehicles(data);
          if (data.length > 0) setSelectedVehicle(data[0].id);
        })
        .catch(() => addToast({ type: 'error', title: 'Error', message: 'Failed to load vehicles' }));
    }
  }, [isAdmin]);

  useEffect(() => {
    fetchTrips();
  }, [isAdmin, selectedVehicle, statusFilter]);

  const fetchTrips = async () => {
    if (!isAdmin && !selectedVehicle) return;
    setLoading(true);
    try {
      let data: TollTrip[];
      if (isAdmin) {
        data = await tollsApi.adminTrips(statusFilter !== 'All' ? { status: statusFilter } : undefined);
      } else {
        data = await tollsApi.trips(selectedVehicle);
      }
      setTrips(data);
      setCurrentPage(1);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load trips';
      addToast({ type: 'error', title: 'Error', message });
    } finally {
      setLoading(false);
    }
  };

  const handleRefundTrip = async (trip: TollTrip) => {
    setIsRefunding(true);
    try {
      await tollsApi.refundTrip(trip.id);
      setRefundedTripIds((prev) => new Set([...prev, trip.id]));
      addToast({ type: 'success', title: 'Refund Processed', message: `PKR ${parseFloat(trip.charge_amount!).toLocaleString()} refunded to ${trip.plate_number}.` });
      setRefundTarget(null);
    } catch (err: unknown) {
      addToast({ type: 'error', title: 'Refund Failed', message: err instanceof Error ? err.message : 'Refund failed' });
    } finally {
      setIsRefunding(false);
    }
  };

  const handleCloseTrip = async (trip: TollTrip) => {
    setClosingTripId(trip.id);
    setConfirmClose(null);
    try {
      const updated = await tollsApi.closeTrip(trip.id);
      setTrips((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      addToast({ type: 'success', title: 'Trip Closed', message: `Trip for ${updated.plate_number} has been force-closed.` });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to close trip';
      addToast({ type: 'error', title: 'Error', message });
    } finally {
      setClosingTripId(null);
    }
  };

  const filtered = useMemo(() => {
    const s = search.toLowerCase();
    return trips.filter((t) => {
      const matchSearch =
        t.plate_number?.toLowerCase().includes(s) ||
        t.entry_plaza_name?.toLowerCase().includes(s) ||
        t.exit_plaza_name?.toLowerCase().includes(s);
      const matchStatus =
        statusFilter === 'All' || !isAdmin || t.status === statusFilter;
      return matchSearch && matchStatus;
    });
  }, [trips, search, statusFilter, isAdmin]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginatedTrips = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  return (
    <div className="animate-fade-in-up">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <Route className="w-6 h-6 text-[var(--accent-blue)]" />
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">Trip History</h1>
          </div>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            {loading ? 'Loading...' : `${filtered.length} trips found`}
          </p>
        </div>
        <button
          onClick={fetchTrips}
          className="flex items-center gap-2 px-4 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-secondary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors self-start"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-4 mb-6 shadow-sm">
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Vehicle selector for non-admin */}
          {!isAdmin && vehicles.length > 0 && (
            <select
              value={selectedVehicle}
              onChange={(e) => setSelectedVehicle(e.target.value)}
              className="px-4 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-blue)]"
            >
              {vehicles.map((v) => (
                <option key={v.id} value={v.id}>{v.plate_number}</option>
              ))}
            </select>
          )}

          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-tertiary)]" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by plate or plaza..."
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
          <div className="flex flex-wrap gap-3 mt-3 pt-3 border-t border-[var(--border-custom)] animate-fade-in-up">
            <div>
              <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">Status</label>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="px-3 py-2 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-lg text-sm text-[var(--text-primary)] outline-none"
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>{s === 'All' ? 'All Status' : s.charAt(0).toUpperCase() + s.slice(1)}</option>
                ))}
              </select>
            </div>
            <button
              onClick={() => { setStatusFilter('All'); setSearch(''); }}
              className="self-end px-3 py-2 text-sm text-[var(--accent-rose)] hover:bg-[var(--accent-rose)]/10 rounded-lg transition-colors"
            >
              Clear
            </button>
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
          ) : paginatedTrips.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <Calendar className="w-12 h-12 text-[var(--text-tertiary)] mx-auto mb-4" />
              <h3 className="text-base font-semibold text-[var(--text-primary)] mb-2">No trips found</h3>
              <p className="text-sm text-[var(--text-secondary)]">
                {search || statusFilter !== 'All'
                  ? 'Try adjusting your filters.'
                  : 'No trips recorded yet.'}
              </p>
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="bg-[var(--bg-elevated)]">
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Plate</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Entry Plaza</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Exit Plaza</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Entry Time</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Exit Time</th>
                  <th className="text-center px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Duration</th>
                  <th className="text-right px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Charge</th>
                  <th className="text-center px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Status</th>
                  {isAdmin && <th className="px-6 py-3" />}
                </tr>
              </thead>
              <tbody>
                {paginatedTrips.map((trip) => (
                  <tr
                    key={trip.id}
                    className="border-b border-[var(--border-custom)] hover:bg-[var(--bg-elevated)] transition-colors"
                  >
                    <td className="px-6 py-4 text-sm font-mono font-semibold text-[var(--text-primary)]">
                      {trip.plate_number}
                    </td>
                    <td className="px-6 py-4 text-sm text-[var(--text-primary)]">{trip.entry_plaza_name}</td>
                    <td className="px-6 py-4 text-sm text-[var(--text-secondary)]">
                      {trip.exit_plaza_name || <span className="text-[var(--text-tertiary)]">In Transit</span>}
                    </td>
                    <td className="px-6 py-4 text-sm text-[var(--text-secondary)]">
                      {new Date(trip.entry_time).toLocaleDateString('en-PK', {
                        day: 'numeric',
                        month: 'short',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </td>
                    <td className="px-6 py-4 text-sm text-[var(--text-secondary)]">
                      {trip.exit_time
                        ? new Date(trip.exit_time).toLocaleDateString('en-PK', {
                            day: 'numeric',
                            month: 'short',
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : <span className="text-[var(--text-tertiary)]">—</span>}
                    </td>
                    <td className="px-6 py-4 text-sm text-[var(--text-secondary)] text-center">
                      {formatDuration(trip.duration_minutes)}
                    </td>
                    <td className="px-6 py-4 text-sm font-semibold text-right">
                      {trip.charge_amount
                        ? <span className="text-[var(--accent-rose)]">PKR {parseFloat(trip.charge_amount).toLocaleString()}</span>
                        : <span className="text-[var(--text-tertiary)]">—</span>}
                    </td>
                    <td className="px-6 py-4 text-center">
                      <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border capitalize ${statusBadge(trip.status)}`}>
                        {trip.status}
                      </span>
                    </td>
                    {isAdmin && (
                      <td className="px-4 py-4 text-center">
                        <div className="flex items-center gap-1.5 justify-center">
                          {trip.status === 'active' && (
                            <button
                              onClick={() => setConfirmClose(trip)}
                              disabled={closingTripId === trip.id}
                              className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-[var(--accent-rose)] border border-[var(--accent-rose)]/30 rounded-lg hover:bg-[var(--accent-rose)]/10 transition-colors disabled:opacity-50"
                            >
                              {closingTripId === trip.id
                                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                : <XCircle className="w-3.5 h-3.5" />}
                              Close
                            </button>
                          )}
                          {trip.status === 'completed' && trip.charge_amount && parseFloat(trip.charge_amount) > 0 && (
                            refundedTripIds.has(trip.id) ? (
                              <span className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-[var(--text-tertiary)] border border-[var(--border-custom)] rounded-lg">
                                <RotateCcw className="w-3.5 h-3.5" />
                                Refunded
                              </span>
                            ) : (
                              <button
                                onClick={() => setRefundTarget(trip)}
                                className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-[var(--accent-amber)] border border-[var(--accent-amber)]/30 rounded-lg hover:bg-[var(--accent-amber)]/10 transition-colors"
                              >
                                <RotateCcw className="w-3.5 h-3.5" />
                                Refund
                              </button>
                            )
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--border-custom)]">
            <p className="text-sm text-[var(--text-secondary)]">
              Page {currentPage} of {totalPages} ({filtered.length} trips)
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="px-4 py-2 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-sm text-[var(--text-secondary)] rounded-lg hover:bg-[var(--bg-surface)] transition-colors disabled:opacity-50"
              >
                Previous
              </button>
              <button
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                className="px-4 py-2 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-sm text-[var(--text-secondary)] rounded-lg hover:bg-[var(--bg-surface)] transition-colors disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Refund confirmation modal */}
      {refundTarget && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setRefundTarget(null)}>
          <div
            className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-2xl p-6 w-full max-w-sm shadow-2xl animate-fade-in-up"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 bg-[var(--accent-amber)]/10 rounded-full flex items-center justify-center">
                <RotateCcw className="w-5 h-5 text-[var(--accent-amber)]" />
              </div>
              <div>
                <p className="font-semibold text-[var(--text-primary)]">Refund Toll Charge</p>
                <p className="text-xs text-[var(--text-secondary)]">{refundTarget.plate_number}</p>
              </div>
            </div>
            <div className="bg-[var(--bg-elevated)] rounded-xl p-3 mb-4 space-y-1.5 text-sm">
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Entry</span>
                <span className="text-[var(--text-primary)]">{refundTarget.entry_plaza_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Exit</span>
                <span className="text-[var(--text-primary)]">{refundTarget.exit_plaza_name || '—'}</span>
              </div>
              <div className="flex justify-between pt-1 border-t border-[var(--border-custom)]">
                <span className="font-medium text-[var(--text-primary)]">Amount to refund</span>
                <span className="font-bold text-[var(--accent-amber)]">
                  PKR {parseFloat(refundTarget.charge_amount!).toLocaleString()}
                </span>
              </div>
            </div>
            <p className="text-sm text-[var(--text-secondary)] mb-5">
              This will credit the toll charge back to the vehicle's M-Tag wallet. This action cannot be undone.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setRefundTarget(null)}
                disabled={isRefunding}
                className="flex-1 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-sm font-medium text-[var(--text-primary)] rounded-xl hover:bg-[var(--bg-surface)] transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => handleRefundTrip(refundTarget)}
                disabled={isRefunding}
                className="flex-1 py-2.5 bg-[var(--accent-amber)] text-white text-sm font-semibold rounded-xl hover:opacity-90 transition-opacity disabled:opacity-60 flex items-center justify-center gap-2"
              >
                {isRefunding ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                {isRefunding ? 'Processing…' : 'Confirm Refund'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Force-close confirmation modal */}
      {confirmClose && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setConfirmClose(null)}>
          <div
            className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-2xl p-6 w-full max-w-sm shadow-2xl animate-fade-in-up"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 bg-[var(--accent-rose)]/10 rounded-full flex items-center justify-center">
                <XCircle className="w-5 h-5 text-[var(--accent-rose)]" />
              </div>
              <div>
                <p className="font-semibold text-[var(--text-primary)]">Force Close Trip</p>
                <p className="text-xs text-[var(--text-secondary)]">{confirmClose.plate_number}</p>
              </div>
            </div>
            <p className="text-sm text-[var(--text-secondary)] mb-5">
              This will mark the trip as <strong>Failed</strong> without charging the vehicle. The gate may not have recorded an exit. Continue?
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmClose(null)}
                className="flex-1 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-sm font-medium text-[var(--text-primary)] rounded-xl hover:bg-[var(--bg-surface)] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleCloseTrip(confirmClose)}
                className="flex-1 py-2.5 bg-[var(--accent-rose)] text-white text-sm font-semibold rounded-xl hover:opacity-90 transition-opacity"
              >
                Force Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
