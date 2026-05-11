import { useNavigate } from 'react-router';
import { useEffect, useState } from 'react';
import CountUp from 'react-countup';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
} from 'recharts';
import {
  Wallet,
  Car,
  Receipt,
  TrendingUp,
  Plus,
  Zap,
  ArrowUpRight,
  Loader2,
} from 'lucide-react';
import { vehiclesApi, tollsApi, accountsApi } from '@/services/api';
import type { StatsData } from '@/services/api';
import type { TollTrip, Account } from '@/types';
import { useAuth } from '@/context/AuthContext';

export default function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [loading, setLoading] = useState(true);
  const [vehicleCount, setVehicleCount] = useState(0);
  const [recentTrips, setRecentTrips] = useState<TollTrip[]>([]);
  const [totalBalance, setTotalBalance] = useState(0);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [stats, setStats] = useState<StatsData | null>(null);

  useEffect(() => {
    const fetchDashboardData = async () => {
      setLoading(true);
      try {
        if (isAdmin) {
          const [statsData, tripsData] = await Promise.all([
            tollsApi.stats(),
            tollsApi.adminTrips().catch(() => []),
          ]);
          setStats(statsData);
          setVehicleCount(statsData.total_vehicles);
          setTotalBalance(statsData.total_balance);
          setRecentTrips(tripsData.slice(0, 8));
        } else {
          const vehicles = await vehiclesApi.list().catch(() => []);
          setVehicleCount(vehicles.length);

          if (vehicles.length > 0) {
            const trips = await tollsApi.trips(vehicles[0].id).catch(() => []);
            setRecentTrips(trips.slice(0, 8));

            const fetchedAccounts: Account[] = [];
            let total = 0;
            for (const v of vehicles) {
              try {
                const acct = await accountsApi.byVehicle(v.id);
                fetchedAccounts.push(acct);
                total += parseFloat(acct.balance || '0');
              } catch {
                // vehicle may not have account
              }
            }
            setAccounts(fetchedAccounts);
            setTotalBalance(total);
          }
        }
      } catch (err) {
        console.error('Dashboard fetch error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, [isAdmin]);

  const completedTrips = recentTrips.filter((t) => t.status === 'completed').length;
  const totalCharge = recentTrips.reduce((sum, t) => sum + parseFloat(t.charge_amount || '0'), 0);

  const kpiCards = [
    {
      title: 'Total Balance',
      value: Math.round(totalBalance),
      prefix: 'PKR ',
      suffix: '',
      icon: Wallet,
      color: 'var(--accent-blue)',
      change: isAdmin
        ? `${stats?.total_vehicles ?? 0} accounts`
        : `${accounts.length} vehicles`,
    },
    {
      title: isAdmin ? 'Total Vehicles' : 'My Vehicles',
      value: vehicleCount,
      prefix: '',
      suffix: '',
      icon: Car,
      color: 'var(--accent-cyan)',
      change: 'Registered',
    },
    {
      title: isAdmin ? 'Total Trips' : 'Toll Charges',
      value: isAdmin ? (stats?.total_trips ?? 0) : Math.round(totalCharge),
      prefix: isAdmin ? '' : 'PKR ',
      suffix: '',
      icon: Receipt,
      color: 'var(--accent-emerald)',
      change: isAdmin ? `${stats?.active_trips ?? 0} active` : `${completedTrips} completed`,
    },
    {
      title: 'Active Plazas',
      value: stats?.active_plazas ?? 0,
      prefix: '',
      suffix: '',
      icon: TrendingUp,
      color: 'var(--accent-amber)',
      change: 'Online',
    },
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-10 h-10 animate-spin text-[var(--accent-blue)]" />
          <p className="text-sm text-[var(--text-secondary)]">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in-up">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Dashboard</h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Welcome back, {user?.full_name || user?.name || 'User'}
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => navigate('/register')}
            className="flex items-center gap-2 px-4 py-2.5 bg-[var(--accent-blue)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity"
          >
            <Plus className="w-4 h-4" />
            Add Vehicle
          </button>
          <button
            onClick={() => navigate('/topup')}
            className="flex items-center gap-2 px-4 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-primary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors"
          >
            <Zap className="w-4 h-4 text-[var(--accent-amber)]" />
            Topup
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {kpiCards.map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.title} className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-5 shadow-sm hover:shadow-md hover:border-[var(--accent-blue)]/30 transition-all duration-300">
              <div className="flex items-start justify-between mb-4">
                <div className="p-2.5 rounded-lg" style={{ backgroundColor: `${card.color}15` }}>
                  <Icon className="w-5 h-5" style={{ color: card.color }} />
                </div>
                <div className="flex items-center gap-1 text-xs font-medium text-[var(--accent-emerald)]">
                  <ArrowUpRight className="w-3.5 h-3.5" />
                  {card.change}
                </div>
              </div>
              <p className="text-2xl font-bold text-[var(--text-primary)]">
                <CountUp end={card.value} duration={2} prefix={card.prefix} suffix={card.suffix} separator="," />
              </p>
              <p className="text-sm text-[var(--text-secondary)] mt-1">{card.title}</p>
            </div>
          );
        })}
      </div>

      {/* Charts — admin only, driven by real stats */}
      {isAdmin && stats && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-6 shadow-sm">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-base font-semibold text-[var(--text-primary)]">Monthly Toll Collection</h3>
              <span className="text-xs text-[var(--accent-emerald)] bg-[var(--accent-emerald)]/10 px-3 py-1 rounded-full">
                Live Data
              </span>
            </div>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={stats.monthly}>
                <defs>
                  <linearGradient id="tollGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--accent-blue)" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="var(--accent-blue)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-custom)" />
                <XAxis dataKey="month" stroke="var(--text-tertiary)" fontSize={12} />
                <YAxis stroke="var(--text-tertiary)" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'var(--bg-surface)',
                    border: '1px solid var(--border-custom)',
                    borderRadius: '12px',
                    fontSize: '12px',
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="toll"
                  name="Revenue (PKR)"
                  stroke="var(--accent-blue)"
                  strokeWidth={2}
                  fill="url(#tollGradient)"
                  activeDot={{ r: 6, fill: 'var(--accent-blue)', strokeWidth: 2, stroke: 'var(--bg-surface)' }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-6 shadow-sm">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-base font-semibold text-[var(--text-primary)]">Daily Transactions</h3>
              <span className="text-xs text-[var(--text-secondary)] bg-[var(--bg-elevated)] px-3 py-1 rounded-full">
                This Week
              </span>
            </div>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={stats.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-custom)" vertical={false} />
                <XAxis dataKey="day" stroke="var(--text-tertiary)" fontSize={12} />
                <YAxis stroke="var(--text-tertiary)" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'var(--bg-surface)',
                    border: '1px solid var(--border-custom)',
                    borderRadius: '12px',
                    fontSize: '12px',
                  }}
                />
                <Bar dataKey="amount" name="Revenue (PKR)" fill="var(--accent-cyan)" radius={[6, 6, 0, 0]} maxBarSize={40} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Recent Trips */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-6 py-5 border-b border-[var(--border-custom)]">
          <h3 className="text-base font-semibold text-[var(--text-primary)]">Recent Trips</h3>
          <button
            onClick={() => navigate('/trips')}
            className="text-sm text-[var(--accent-blue)] hover:underline"
          >
            View All
          </button>
        </div>
        <div className="overflow-x-auto">
          {recentTrips.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <Receipt className="w-10 h-10 text-[var(--text-tertiary)] mx-auto mb-3" />
              <p className="text-sm text-[var(--text-secondary)]">No trips found</p>
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="bg-[var(--bg-elevated)]">
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Plate</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Entry Plaza</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Exit Plaza</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Entry Time</th>
                  <th className="text-right px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Charge</th>
                  <th className="text-center px-6 py-3 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">Status</th>
                </tr>
              </thead>
              <tbody>
                {recentTrips.map((trip, index) => (
                  <tr
                    key={trip.id}
                    className={`border-b border-[var(--border-custom)] hover:bg-[var(--bg-elevated)] transition-all duration-200 ${
                      index === 0 ? 'animate-stream-in' : ''
                    }`}
                  >
                    <td className="px-6 py-4 text-sm font-mono text-[var(--text-primary)]">{trip.plate_number}</td>
                    <td className="px-6 py-4 text-sm text-[var(--text-primary)]">{trip.entry_plaza_name}</td>
                    <td className="px-6 py-4 text-sm text-[var(--text-secondary)]">{trip.exit_plaza_name || '—'}</td>
                    <td className="px-6 py-4 text-sm text-[var(--text-secondary)]">
                      {new Date(trip.entry_time).toLocaleDateString('en-PK', {
                        day: 'numeric',
                        month: 'short',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </td>
                    <td className="px-6 py-4 text-sm font-semibold text-[var(--text-primary)] text-right">
                      {trip.charge_amount ? `PKR ${parseFloat(trip.charge_amount).toLocaleString()}` : '—'}
                    </td>
                    <td className="px-6 py-4 text-center">
                      <span
                        className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${
                          trip.status === 'completed'
                            ? 'bg-[var(--accent-emerald)]/10 text-[var(--accent-emerald)] border-[var(--accent-emerald)]/20'
                            : trip.status === 'active'
                            ? 'bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border-[var(--accent-blue)]/20'
                            : 'bg-[var(--accent-rose)]/10 text-[var(--accent-rose)] border-[var(--accent-rose)]/20'
                        }`}
                      >
                        {trip.status.charAt(0).toUpperCase() + trip.status.slice(1)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
