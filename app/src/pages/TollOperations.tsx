import { useState, useEffect } from 'react';
import { tollsApi, accountsApi, ApiError } from '@/services/api';
import type { Plaza, TollTrip } from '@/types';
import { useToast } from '@/context/ToastContext';
import { useAuth } from '@/context/AuthContext';
import { useNavigate } from 'react-router';
import {
  ArrowRight,
  ArrowLeft,
  Loader2,
  CheckCircle,
  XCircle,
  Clock,
  RefreshCw,
  Gauge,
  Wallet,
  AlertTriangle,
  Radio,
} from 'lucide-react';

interface LowBalanceAlert {
  tagSerial: string;
  currentBalance?: string;
  minimumRequired?: string;
  charge?: string;
  mode: 'entry' | 'exit';
}

interface OperationResult {
  success: boolean;
  trip?: TollTrip;
  message: string;
  type: 'entry' | 'exit';
}

interface OpLog {
  id: string;
  time: string;
  type: 'entry' | 'exit';
  tag_serial: string;
  plaza: string;
  result: OperationResult;
}

interface GateEvent {
  id: number;
  plaza: string;
  lane: number | null;
  created_at: string;
  executed_at: string | null;
  status: 'pending' | 'executed';
}

export default function TollOperations() {
  const { addToast } = useToast();
  const { user } = useAuth();
  const navigate = useNavigate();

  const isAllowed = user?.role === 'admin' || user?.role === 'operator';

  const [plazas, setPlazas] = useState<Plaza[]>([]);
  const [loadingPlazas, setLoadingPlazas] = useState(true);

  // Entry form
  const [entryTag, setEntryTag] = useState('');
  const [entryPlaza, setEntryPlaza] = useState('');
  const [entryLane, setEntryLane] = useState('');
  const [processingEntry, setProcessingEntry] = useState(false);

  // Exit form
  const [exitTag, setExitTag] = useState('');
  const [exitPlaza, setExitPlaza] = useState('');
  const [exitLane, setExitLane] = useState('');
  const [processingExit, setProcessingExit] = useState(false);

  // Logs
  const [opLogs, setOpLogs] = useState<OpLog[]>([]);

  // Low balance top-up
  const [lowBalance, setLowBalance] = useState<LowBalanceAlert | null>(null);
  const [topupAmount, setTopupAmount] = useState('');
  const [processingTopup, setProcessingTopup] = useState(false);

  // Gate events (admin only)
  const [gateEvents, setGateEvents] = useState<GateEvent[]>([]);
  const [loadingGateEvents, setLoadingGateEvents] = useState(false);
  const [showGateEvents, setShowGateEvents] = useState(false);

  useEffect(() => {
    if (!isAllowed) return;
    const fetchPlazas = async () => {
      setLoadingPlazas(true);
      try {
        const data = await tollsApi.plazas();
        setPlazas(data);
        if (data.length > 0) {
          setEntryPlaza(data[0].id);
          setExitPlaza(data[0].id);
        }
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Failed to load plazas';
        addToast({ type: 'error', title: 'Error', message });
      } finally {
        setLoadingPlazas(false);
      }
    };
    fetchPlazas();
  }, [isAllowed]);

  if (!isAllowed) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
        <XCircle className="w-16 h-16 text-[var(--accent-rose)] mb-4" />
        <h2 className="text-xl font-bold text-[var(--text-primary)] mb-2">Access Restricted</h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          Toll Operations is only available to operators and admins.
        </p>
        <button
          onClick={() => navigate('/dashboard')}
          className="px-6 py-2.5 bg-[var(--accent-blue)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity"
        >
          Go to Dashboard
        </button>
      </div>
    );
  }

  const getEntryPlazaLanes = () => plazas.find((p) => p.id === entryPlaza)?.lanes || [];
  const getExitPlazaLanes = () => plazas.find((p) => p.id === exitPlaza)?.lanes || [];

  const addLog = (type: 'entry' | 'exit', tag_serial: string, plazaId: string, result: OperationResult) => {
    const plaza = plazas.find((p) => p.id === plazaId);
    const log: OpLog = {
      id: Date.now().toString(),
      time: new Date().toLocaleTimeString('en-PK'),
      type,
      tag_serial,
      plaza: plaza?.name || plazaId,
      result,
    };
    setOpLogs((prev) => [log, ...prev].slice(0, 10));
  };

  const handleEntry = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!entryTag.trim() || !entryPlaza) {
      addToast({ type: 'error', title: 'Validation', message: 'Tag serial and plaza are required.' });
      return;
    }
    setProcessingEntry(true);
    setLowBalance(null);
    try {
      const trip = await tollsApi.entry({
        tag_serial: entryTag,
        plaza_id: entryPlaza,
        ...(entryLane ? { lane_id: entryLane } : {}),
      });
      const result: OperationResult = { success: true, trip, message: 'Entry recorded successfully', type: 'entry' };
      addLog('entry', entryTag, entryPlaza, result);
      addToast({ type: 'success', title: 'Entry Recorded', message: `Vehicle entered at ${plazas.find((p) => p.id === entryPlaza)?.name}` });
      setEntryTag('');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Entry failed';
      const result: OperationResult = { success: false, message, type: 'entry' };
      addLog('entry', entryTag, entryPlaza, result);
      if (err instanceof ApiError && message.toLowerCase().includes('insufficient balance')) {
        setLowBalance({
          tagSerial: entryTag,
          currentBalance: err.errors?.current_balance as string | undefined,
          minimumRequired: err.errors?.minimum_required as string | undefined,
          mode: 'entry',
        });
        setTopupAmount('');
      } else {
        addToast({ type: 'error', title: 'Entry Failed', message });
      }
    } finally {
      setProcessingEntry(false);
    }
  };

  const handleExit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!exitTag.trim() || !exitPlaza) {
      addToast({ type: 'error', title: 'Validation', message: 'Tag serial and plaza are required.' });
      return;
    }
    setProcessingExit(true);
    setLowBalance(null);
    try {
      const trip = await tollsApi.exit({
        tag_serial: exitTag,
        plaza_id: exitPlaza,
        ...(exitLane ? { lane_id: exitLane } : {}),
      });
      const result: OperationResult = { success: true, trip, message: 'Exit processed successfully', type: 'exit' };
      addLog('exit', exitTag, exitPlaza, result);
      const charge = trip.charge_amount ? `PKR ${parseFloat(trip.charge_amount).toLocaleString()} charged` : '';
      addToast({ type: 'success', title: 'Exit Processed', message: charge || 'Vehicle exited successfully' });
      setExitTag('');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Exit failed';
      const result: OperationResult = { success: false, message, type: 'exit' };
      addLog('exit', exitTag, exitPlaza, result);
      if (err instanceof ApiError && message.toLowerCase().includes('insufficient balance')) {
        setLowBalance({
          tagSerial: exitTag,
          currentBalance: err.errors?.current_balance as string | undefined,
          charge: err.errors?.charge as string | undefined,
          mode: 'exit',
        });
        setTopupAmount('');
      } else {
        addToast({ type: 'error', title: 'Exit Failed', message });
      }
    } finally {
      setProcessingExit(false);
    }
  };

  const handleTopup = async () => {
    if (!lowBalance || !topupAmount.trim()) return;
    const amount = parseFloat(topupAmount);
    if (isNaN(amount) || amount <= 0) {
      addToast({ type: 'error', title: 'Validation', message: 'Enter a valid amount.' });
      return;
    }
    setProcessingTopup(true);
    try {
      const res = await accountsApi.operatorTopup(lowBalance.tagSerial, amount);
      addToast({
        type: 'success',
        title: 'Balance Added',
        message: `Rs.${parseFloat(res.amount_added).toLocaleString()} added to ${res.plate_number}. Processing ${lowBalance.mode}...`,
      });

      // Auto-process entry/exit — no re-scan needed
      const plazaId = lowBalance.mode === 'entry' ? entryPlaza : exitPlaza;
      const laneId  = lowBalance.mode === 'entry' ? entryLane  : exitLane;
      const payload = {
        tag_serial: lowBalance.tagSerial,
        plaza_id: plazaId,
        ...(laneId ? { lane_id: laneId } : {}),
      };

      if (lowBalance.mode === 'entry') {
        const trip = await tollsApi.entry(payload);
        const result: OperationResult = { success: true, trip, message: 'Entry recorded after top-up', type: 'entry' };
        addLog('entry', lowBalance.tagSerial, plazaId, result);
        addToast({ type: 'success', title: 'Gate Open', message: `Entry recorded at ${plazas.find((p) => p.id === plazaId)?.name}` });
        setEntryTag('');
      } else {
        const trip = await tollsApi.exit(payload);
        const result: OperationResult = { success: true, trip, message: 'Exit processed after top-up', type: 'exit' };
        addLog('exit', lowBalance.tagSerial, plazaId, result);
        const charge = trip.charge_amount ? `PKR ${parseFloat(trip.charge_amount).toLocaleString()} charged` : '';
        addToast({ type: 'success', title: 'Gate Open', message: charge || 'Exit processed successfully' });
        setExitTag('');
      }

      setLowBalance(null);
      setTopupAmount('');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Operation failed';
      addToast({ type: 'error', title: 'Failed', message });
    } finally {
      setProcessingTopup(false);
    }
  };

  const fetchGateEvents = async () => {
    setLoadingGateEvents(true);
    try {
      const data = await tollsApi.gateEvents();
      setGateEvents(data as GateEvent[]);
    } finally {
      setLoadingGateEvents(false);
    }
  };

  const inputClass =
    'w-full px-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--accent-blue)] focus:ring-2 focus:ring-[var(--accent-blue)]/20 transition-all';

  return (
    <div className="animate-fade-in-up">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <Gauge className="w-6 h-6 text-[var(--accent-blue)]" />
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Toll Operations</h1>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mt-1">
          Process vehicle entry and exit at toll plazas
        </p>
      </div>

      {/* Minimum balance notice */}
      <div className="flex items-center gap-2 px-4 py-2.5 bg-[var(--accent-amber)]/5 border border-[var(--accent-amber)]/20 rounded-xl mb-4 text-sm text-[var(--text-secondary)]">
        <AlertTriangle className="w-4 h-4 text-[var(--accent-amber)] flex-shrink-0" />
        <span>Minimum account balance required for entry: <strong className="text-[var(--text-primary)]">PKR 50</strong>. Top up before processing if balance is insufficient.</span>
      </div>

      {loadingPlazas ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-[var(--accent-blue)]" />
        </div>
      ) : (
        <>
          {/* Two Panels */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            {/* Entry Panel */}
            <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl shadow-sm overflow-hidden">
              <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--border-custom)] bg-[var(--accent-emerald)]/5">
                <div className="p-2 bg-[var(--accent-emerald)]/10 rounded-lg">
                  <ArrowRight className="w-5 h-5 text-[var(--accent-emerald)]" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-[var(--text-primary)]">Vehicle Entry</h2>
                  <p className="text-xs text-[var(--text-secondary)]">Record vehicle entering the expressway</p>
                </div>
              </div>
              <form onSubmit={handleEntry} className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                    M-Tag Serial <span className="text-[var(--accent-rose)]">*</span>
                  </label>
                  <input
                    type="text"
                    value={entryTag}
                    onChange={(e) => setEntryTag(e.target.value)}
                    placeholder="MTAG-XXXXXXXX"
                    className={inputClass}
                    autoComplete="off"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                    Plaza <span className="text-[var(--accent-rose)]">*</span>
                  </label>
                  <select
                    value={entryPlaza}
                    onChange={(e) => { setEntryPlaza(e.target.value); setEntryLane(''); }}
                    className={inputClass}
                  >
                    <option value="">Select Plaza</option>
                    {plazas.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
                {entryPlaza && getEntryPlazaLanes().length > 0 && (
                  <div>
                    <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">Lane (optional)</label>
                    <select
                      value={entryLane}
                      onChange={(e) => setEntryLane(e.target.value)}
                      className={inputClass}
                    >
                      <option value="">Auto-assign</option>
                      {getEntryPlazaLanes().filter((l) => l.is_active).map((l) => (
                        <option key={l.id} value={l.id}>Lane {l.lane_number}</option>
                      ))}
                    </select>
                  </div>
                )}
                <button
                  type="submit"
                  disabled={processingEntry}
                  className="w-full py-3 bg-[var(--accent-emerald)] text-white text-sm font-semibold rounded-xl hover:opacity-90 transition-opacity disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {processingEntry ? (
                    <><Loader2 className="w-4 h-4 animate-spin" />Processing...</>
                  ) : (
                    <><ArrowRight className="w-4 h-4" />Record Entry</>
                  )}
                </button>
              </form>
            </div>

            {/* Exit Panel */}
            <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl shadow-sm overflow-hidden">
              <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--border-custom)] bg-[var(--accent-rose)]/5">
                <div className="p-2 bg-[var(--accent-rose)]/10 rounded-lg">
                  <ArrowLeft className="w-5 h-5 text-[var(--accent-rose)]" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-[var(--text-primary)]">Vehicle Exit</h2>
                  <p className="text-xs text-[var(--text-secondary)]">Process vehicle exiting and calculate charge</p>
                </div>
              </div>
              <form onSubmit={handleExit} className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                    M-Tag Serial <span className="text-[var(--accent-rose)]">*</span>
                  </label>
                  <input
                    type="text"
                    value={exitTag}
                    onChange={(e) => setExitTag(e.target.value)}
                    placeholder="MTAG-XXXXXXXX"
                    className={inputClass}
                    autoComplete="off"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                    Plaza <span className="text-[var(--accent-rose)]">*</span>
                  </label>
                  <select
                    value={exitPlaza}
                    onChange={(e) => { setExitPlaza(e.target.value); setExitLane(''); }}
                    className={inputClass}
                  >
                    <option value="">Select Plaza</option>
                    {plazas.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
                {exitPlaza && getExitPlazaLanes().length > 0 && (
                  <div>
                    <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">Lane (optional)</label>
                    <select
                      value={exitLane}
                      onChange={(e) => setExitLane(e.target.value)}
                      className={inputClass}
                    >
                      <option value="">Auto-assign</option>
                      {getExitPlazaLanes().filter((l) => l.is_active).map((l) => (
                        <option key={l.id} value={l.id}>Lane {l.lane_number}</option>
                      ))}
                    </select>
                  </div>
                )}
                <button
                  type="submit"
                  disabled={processingExit}
                  className="w-full py-3 bg-[var(--accent-rose)] text-white text-sm font-semibold rounded-xl hover:opacity-90 transition-opacity disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {processingExit ? (
                    <><Loader2 className="w-4 h-4 animate-spin" />Processing...</>
                  ) : (
                    <><ArrowLeft className="w-4 h-4" />Process Exit</>
                  )}
                </button>
              </form>
            </div>
          </div>

          {/* Low Balance / Cash Top-up Panel */}
          {lowBalance && (
            <div className="bg-[var(--bg-surface)] border-2 border-amber-400/50 rounded-xl shadow-sm overflow-hidden">
              <div className="flex items-center gap-3 px-6 py-4 border-b border-amber-400/30 bg-amber-400/5">
                <div className="p-2 bg-amber-400/10 rounded-lg">
                  <AlertTriangle className="w-5 h-5 text-amber-500" />
                </div>
                <div className="flex-1">
                  <h2 className="text-base font-semibold text-[var(--text-primary)]">Low Balance — Cash Top-Up Required</h2>
                  <p className="text-xs text-[var(--text-secondary)]">
                    Tag: <span className="font-mono font-semibold">{lowBalance.tagSerial}</span>
                    {lowBalance.currentBalance && (
                      <> &nbsp;|&nbsp; Current balance: <span className="font-semibold text-[var(--accent-rose)]">Rs.{parseFloat(lowBalance.currentBalance).toLocaleString()}</span></>
                    )}
                    {lowBalance.minimumRequired && (
                      <> &nbsp;|&nbsp; Minimum required: <span className="font-semibold">Rs.{parseFloat(lowBalance.minimumRequired).toLocaleString()}</span></>
                    )}
                    {lowBalance.charge && (
                      <> &nbsp;|&nbsp; Toll charge: <span className="font-semibold">Rs.{parseFloat(lowBalance.charge).toLocaleString()}</span></>
                    )}
                  </p>
                </div>
                <button
                  onClick={() => setLowBalance(null)}
                  className="text-xs text-[var(--text-tertiary)] hover:text-[var(--accent-rose)] transition-colors"
                >
                  Dismiss
                </button>
              </div>
              <div className="p-6 flex items-end gap-4">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                    Cash Received (Rs.) <span className="text-[var(--accent-rose)]">*</span>
                  </label>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={topupAmount}
                    onChange={(e) => setTopupAmount(e.target.value)}
                    placeholder="e.g. 200"
                    className={inputClass}
                    autoFocus
                  />
                </div>
                <button
                  onClick={handleTopup}
                  disabled={processingTopup || !topupAmount.trim()}
                  className="px-6 py-3 bg-amber-500 text-white text-sm font-semibold rounded-xl hover:opacity-90 transition-opacity disabled:opacity-60 flex items-center gap-2 whitespace-nowrap"
                >
                  {processingTopup ? (
                    <><Loader2 className="w-4 h-4 animate-spin" />Adding...</>
                  ) : (
                    <><Wallet className="w-4 h-4" />Add Balance</>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Gate Events (admin only) */}
          {user?.role === 'admin' && (
            <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl shadow-sm overflow-hidden mb-6">
              <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-custom)]">
                <div className="flex items-center gap-2">
                  <Radio className="w-5 h-5 text-[var(--accent-cyan)]" />
                  <h3 className="text-base font-semibold text-[var(--text-primary)]">Gate Signal Log</h3>
                  <span className="px-2 py-0.5 bg-[var(--bg-elevated)] text-[var(--text-tertiary)] text-xs rounded-full">Hardware</span>
                </div>
                <button
                  onClick={() => {
                    if (!showGateEvents) fetchGateEvents();
                    setShowGateEvents((v) => !v);
                  }}
                  className="text-xs text-[var(--accent-blue)] hover:underline flex items-center gap-1"
                >
                  {showGateEvents ? 'Hide' : 'Show'}
                </button>
              </div>

              {showGateEvents && (
                <>
                  <div className="flex items-center justify-between px-6 py-2 border-b border-[var(--border-custom)] bg-[var(--bg-elevated)]">
                    <span className="text-xs text-[var(--text-tertiary)]">Last 100 gate open commands sent from this portal to hardware</span>
                    <button
                      onClick={fetchGateEvents}
                      disabled={loadingGateEvents}
                      className="text-xs text-[var(--text-secondary)] hover:text-[var(--accent-blue)] flex items-center gap-1 transition-colors"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${loadingGateEvents ? 'animate-spin' : ''}`} />
                      Refresh
                    </button>
                  </div>
                  {loadingGateEvents ? (
                    <div className="flex items-center justify-center py-10">
                      <Loader2 className="w-6 h-6 animate-spin text-[var(--accent-cyan)]" />
                    </div>
                  ) : gateEvents.length === 0 ? (
                    <div className="px-6 py-10 text-center text-sm text-[var(--text-tertiary)]">No gate events recorded yet.</div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full">
                        <thead>
                          <tr className="bg-[var(--bg-elevated)]">
                            <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Time</th>
                            <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Plaza</th>
                            <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Lane</th>
                            <th className="text-center px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Executed At</th>
                            <th className="text-center px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {gateEvents.map((ev) => (
                            <tr key={ev.id} className="border-b border-[var(--border-custom)] hover:bg-[var(--bg-elevated)] transition-colors">
                              <td className="px-6 py-3 text-xs text-[var(--text-secondary)]">
                                {new Date(ev.created_at).toLocaleTimeString('en-PK', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                              </td>
                              <td className="px-6 py-3 text-sm text-[var(--text-primary)]">{ev.plaza}</td>
                              <td className="px-6 py-3 text-sm text-[var(--text-secondary)]">{ev.lane ? `Lane ${ev.lane}` : 'Any'}</td>
                              <td className="px-6 py-3 text-xs text-center text-[var(--text-secondary)]">
                                {ev.executed_at
                                  ? new Date(ev.executed_at).toLocaleTimeString('en-PK', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                                  : <span className="text-[var(--text-tertiary)]">—</span>}
                              </td>
                              <td className="px-6 py-3 text-center">
                                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${
                                  ev.status === 'executed'
                                    ? 'bg-[var(--accent-emerald)]/10 text-[var(--accent-emerald)] border-[var(--accent-emerald)]/20'
                                    : 'bg-[var(--accent-amber)]/10 text-[var(--accent-amber)] border-[var(--accent-amber)]/20'
                                }`}>
                                  {ev.status === 'executed' ? 'Executed' : 'Pending'}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Operations Log */}
          <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-custom)]">
              <div className="flex items-center gap-2">
                <Clock className="w-5 h-5 text-[var(--accent-blue)]" />
                <h3 className="text-base font-semibold text-[var(--text-primary)]">Recent Operations</h3>
              </div>
              <button
                onClick={() => setOpLogs([])}
                className="text-xs text-[var(--text-secondary)] hover:text-[var(--accent-rose)] transition-colors flex items-center gap-1"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Clear
              </button>
            </div>

            {opLogs.length === 0 ? (
              <div className="px-6 py-12 text-center">
                <Clock className="w-10 h-10 text-[var(--text-tertiary)] mx-auto mb-3" />
                <p className="text-sm text-[var(--text-secondary)]">No operations yet. Use the panels above to process vehicles.</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-[var(--bg-elevated)]">
                      <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Time</th>
                      <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Type</th>
                      <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Tag Serial</th>
                      <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Plaza</th>
                      <th className="text-right px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Charge</th>
                      <th className="text-center px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {opLogs.map((log) => (
                      <tr
                        key={log.id}
                        className="border-b border-[var(--border-custom)] hover:bg-[var(--bg-elevated)] transition-colors"
                      >
                        <td className="px-6 py-4 text-sm text-[var(--text-secondary)]">{log.time}</td>
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${
                              log.type === 'entry'
                                ? 'bg-[var(--accent-emerald)]/10 text-[var(--accent-emerald)] border-[var(--accent-emerald)]/20'
                                : 'bg-[var(--accent-rose)]/10 text-[var(--accent-rose)] border-[var(--accent-rose)]/20'
                            }`}
                          >
                            {log.type === 'entry' ? <ArrowRight className="w-3 h-3" /> : <ArrowLeft className="w-3 h-3" />}
                            {log.type.charAt(0).toUpperCase() + log.type.slice(1)}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-sm font-mono text-[var(--text-primary)]">{log.tag_serial}</td>
                        <td className="px-6 py-4 text-sm text-[var(--text-secondary)]">{log.plaza}</td>
                        <td className="px-6 py-4 text-sm text-right">
                          {log.result.trip?.charge_amount
                            ? <span className="font-semibold text-[var(--accent-rose)]">PKR {parseFloat(log.result.trip.charge_amount).toLocaleString()}</span>
                            : <span className="text-[var(--text-tertiary)]">—</span>}
                        </td>
                        <td className="px-6 py-4 text-center">
                          {log.result.success ? (
                            <CheckCircle className="w-5 h-5 text-[var(--accent-emerald)] mx-auto" />
                          ) : (
                            <XCircle className="w-5 h-5 text-[var(--accent-rose)] mx-auto" />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
