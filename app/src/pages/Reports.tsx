import { useState, useEffect } from 'react';
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import { Download, TrendingUp, FileText, Wallet, MapPin, Loader2 } from 'lucide-react';
import { useToast } from '@/context/ToastContext';
import { tollsApi } from '@/services/api';
import type { StatsData } from '@/services/api';

const COLORS = ['#3B82F6', '#06B6D4', '#10B981', '#F59E0B', '#F43F5E', '#8B5CF6'];

export default function Reports() {
  const { addToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<StatsData | null>(null);

  useEffect(() => {
    tollsApi
      .stats()
      .then(setStats)
      .catch(() => addToast({ type: 'error', title: 'Error', message: 'Failed to load report data' }))
      .finally(() => setLoading(false));
  }, []);

  const downloadReport = () => {
    if (!stats) return;

    const rows = [
      ['Month', 'Revenue (PKR)', 'Transactions'],
      ...stats.monthly.map((m) => [m.month, m.toll.toFixed(2), m.transactions]),
      [],
      ['Day', 'Revenue (PKR)', 'Trip Count'],
      ...stats.daily.map((d) => [d.day, d.amount.toFixed(2), d.count]),
      [],
      ['Plaza', 'Revenue (PKR)', 'Trips'],
      ...stats.plaza_stats.map((p) => [p.name, p.revenue.toFixed(2), p.trips]),
    ];

    const csv = rows.map((r) => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `mtag-report-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    addToast({ type: 'success', title: 'Downloaded', message: 'Report CSV saved.' });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-10 h-10 animate-spin text-[var(--accent-blue)]" />
          <p className="text-sm text-[var(--text-secondary)]">Loading analytics...</p>
        </div>
      </div>
    );
  }

  if (!stats) return null;

  const summaryCards = [
    {
      title: 'Total Revenue',
      value: `PKR ${(stats.total_revenue / 1000).toFixed(1)}K`,
      sub: `${stats.completed_trips} completed trips`,
      icon: TrendingUp,
      color: 'var(--accent-emerald)',
    },
    {
      title: 'Total Trips',
      value: stats.total_trips.toLocaleString(),
      sub: `${stats.active_trips} active`,
      icon: FileText,
      color: 'var(--accent-blue)',
    },
    {
      title: 'Total Wallet Balance',
      value: `PKR ${(stats.total_balance / 1000).toFixed(1)}K`,
      sub: `${stats.total_vehicles} accounts`,
      icon: Wallet,
      color: 'var(--accent-cyan)',
    },
    {
      title: 'Active Plazas',
      value: String(stats.active_plazas),
      sub: `${stats.plaza_stats.length} total plazas`,
      icon: MapPin,
      color: 'var(--accent-amber)',
    },
  ];

  const maxPlazaRevenue = Math.max(...stats.plaza_stats.map((p) => p.revenue), 1);

  return (
    <div className="animate-fade-in-up">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Reports & Analytics</h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Live toll collection analytics
          </p>
        </div>
        <button
          onClick={downloadReport}
          className="flex items-center gap-2 px-4 py-2.5 bg-[var(--accent-blue)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity self-start"
        >
          <Download className="w-4 h-4" />
          Download CSV
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        {summaryCards.map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.title} className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-5 shadow-sm">
              <div className="flex items-center gap-3 mb-3">
                <div className="p-2 rounded-lg" style={{ backgroundColor: `${card.color}15` }}>
                  <Icon className="w-5 h-5" style={{ color: card.color }} />
                </div>
                <span className="text-xs text-[var(--text-secondary)]">{card.sub}</span>
              </div>
              <p className="text-2xl font-bold text-[var(--text-primary)]">{card.value}</p>
              <p className="text-sm text-[var(--text-secondary)] mt-1">{card.title}</p>
            </div>
          );
        })}
      </div>

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Monthly Revenue Bar Chart */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-6">
            <h3 className="text-base font-semibold text-[var(--text-primary)]">Monthly Toll Revenue</h3>
            <span className="text-xs text-[var(--accent-emerald)] bg-[var(--accent-emerald)]/10 px-2 py-1 rounded-full">Live</span>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={stats.monthly}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-custom)" vertical={false} />
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
              <Legend />
              <Bar dataKey="toll" name="Revenue (PKR)" fill="var(--accent-blue)" radius={[8, 8, 0, 0]} maxBarSize={50} />
              <Bar dataKey="transactions" name="Trips" fill="var(--accent-cyan)" radius={[8, 8, 0, 0]} maxBarSize={50} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Daily Revenue Line Chart */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-6">
            <h3 className="text-base font-semibold text-[var(--text-primary)]">Daily Transactions (Last 7 Days)</h3>
            <span className="text-xs text-[var(--accent-emerald)] bg-[var(--accent-emerald)]/10 px-2 py-1 rounded-full">Live</span>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={stats.daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-custom)" />
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
              <Legend />
              <Line
                type="monotone"
                dataKey="amount"
                name="Revenue (PKR)"
                stroke="var(--accent-emerald)"
                strokeWidth={3}
                dot={{ fill: 'var(--accent-emerald)', strokeWidth: 2, r: 5, stroke: 'var(--bg-surface)' }}
                activeDot={{ r: 7, fill: 'var(--accent-emerald)', stroke: 'var(--bg-surface)', strokeWidth: 3 }}
              />
              <Line
                type="monotone"
                dataKey="count"
                name="Trip Count"
                stroke="var(--accent-amber)"
                strokeWidth={2}
                strokeDasharray="5 5"
                dot={{ fill: 'var(--accent-amber)', strokeWidth: 2, r: 4, stroke: 'var(--bg-surface)' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Plaza Revenue */}
        <div className="lg:col-span-2 bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-6 shadow-sm">
          <h3 className="text-base font-semibold text-[var(--text-primary)] mb-6">Plaza Revenue</h3>
          {stats.plaza_stats.length === 0 ? (
            <div className="flex items-center justify-center h-40 text-sm text-[var(--text-secondary)]">
              No plaza data yet
            </div>
          ) : (
            <div className="space-y-5">
              {stats.plaza_stats
                .sort((a, b) => b.revenue - a.revenue)
                .map((plaza) => {
                  const pct = Math.round((plaza.revenue / maxPlazaRevenue) * 100);
                  return (
                    <div key={plaza.name}>
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-medium text-[var(--text-primary)]">{plaza.name}</span>
                          <span
                            className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                              plaza.is_active
                                ? 'bg-[var(--accent-emerald)]/10 text-[var(--accent-emerald)]'
                                : 'bg-[var(--accent-rose)]/10 text-[var(--accent-rose)]'
                            }`}
                          >
                            {plaza.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </div>
                        <div className="text-right">
                          <span className="text-sm font-semibold text-[var(--text-primary)]">
                            PKR {plaza.revenue.toLocaleString()}
                          </span>
                          <span className="text-xs text-[var(--text-secondary)] ml-2">
                            {plaza.trips} trips
                          </span>
                        </div>
                      </div>
                      <div className="h-2.5 bg-[var(--bg-elevated)] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-700"
                          style={{
                            width: `${pct}%`,
                            backgroundColor: 'var(--accent-blue)',
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
            </div>
          )}
        </div>

        {/* Vehicle Type Distribution */}
        <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-6 shadow-sm">
          <h3 className="text-base font-semibold text-[var(--text-primary)] mb-6">Vehicle Distribution</h3>
          {stats.vehicle_type_breakdown.length === 0 ? (
            <div className="flex items-center justify-center h-40 text-sm text-[var(--text-secondary)]">
              No vehicles registered
            </div>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={stats.vehicle_type_breakdown}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={90}
                    paddingAngle={4}
                    dataKey="value"
                  >
                    {stats.vehicle_type_breakdown.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-custom)',
                      borderRadius: '12px',
                      fontSize: '12px',
                    }}
                    formatter={(value, name, props) => [`${props.payload.count} (${value}%)`, props.payload.name]}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-2 mt-4">
                {stats.vehicle_type_breakdown.map((item, index) => (
                  <div key={item.name} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-3 h-3 rounded-full" style={{ backgroundColor: COLORS[index % COLORS.length] }} />
                      <span className="text-sm text-[var(--text-secondary)]">{item.name}</span>
                    </div>
                    <span className="text-sm font-medium text-[var(--text-primary)]">{item.value}%</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
