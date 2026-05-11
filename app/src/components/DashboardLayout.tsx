import { Outlet, useLocation, useNavigate } from 'react-router';
import { useState, useEffect, useRef } from 'react';
import { useAuth } from '@/context/AuthContext';
import { useTheme } from '@/context/ThemeContext';
import {
  LayoutDashboard,
  CreditCard,
  Car,
  History,
  BarChart3,
  User,
  LogOut,
  Menu,
  Search,
  Bell,
  Sun,
  Moon,
  ChevronDown,
  MapPin,
  Route,
  Users,
  Gauge,
  ArrowRightLeft,
  Wallet,
} from 'lucide-react';

interface NavItem {
  path: string;
  label: string;
  icon: React.ElementType;
  adminOnly?: boolean;
}

const navItems: NavItem[] = [
  { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/register', label: 'M-Tag Registration', icon: CreditCard },
  { path: '/vehicles', label: 'Vehicles', icon: Car },
  { path: '/operations', label: 'Toll Operations', icon: Gauge },
  { path: '/trips', label: 'Trip History', icon: Route },
  { path: '/transactions', label: 'Transactions', icon: History },
  { path: '/topup', label: 'Balance Topup', icon: Wallet },
  { path: '/transfer', label: 'Balance Transfer', icon: ArrowRightLeft },
  { path: '/plazas', label: 'Plazas & Rates', icon: MapPin },
  { path: '/reports', label: 'Reports', icon: BarChart3 },
  { path: '/profile', label: 'Profile', icon: User },
  { path: '/admin/users', label: 'User Management', icon: Users, adminOnly: true },
];

export default function DashboardLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { isDark, toggleTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);

  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(event.target as Node)) {
        setProfileOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  const visibleNavItems = navItems.filter((item) => !item.adminOnly || isAdmin);

  return (
    <div className="min-h-screen bg-[var(--bg-body)]">
      {/* Sidebar */}
      <aside
        className={`fixed top-0 left-0 z-40 h-full w-[280px] bg-[var(--bg-body)] border-r border-[var(--border-custom)] transform transition-transform duration-300 ease-out ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="flex items-center gap-3 px-6 py-5 border-b border-[var(--border-custom)]">
          <img src="/logo.png" alt="Logo" className="w-10 h-10" />
          <div className="flex-1 min-w-0">
            <h1 className="text-sm font-bold text-[var(--text-primary)] leading-tight">
              Smart Expressway
            </h1>
            <p className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wider">
              Toll System
            </p>
          </div>
        </div>

        <nav className="p-4 space-y-1 overflow-y-auto max-h-[calc(100vh-140px)]">
          {visibleNavItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 relative group ${
                  isActive
                    ? 'bg-[var(--accent-blue)]/10 text-[var(--accent-blue)]'
                    : 'text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]'
                }`}
              >
                {isActive && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-[var(--accent-blue)] rounded-r-full" />
                )}
                <Icon className={`w-5 h-5 ${isActive ? 'text-[var(--accent-blue)]' : ''}`} />
                {item.label}
                {item.adminOnly && (
                  <span className="ml-auto text-[10px] bg-[var(--accent-amber)]/20 text-[var(--accent-amber)] px-1.5 py-0.5 rounded-full">
                    Admin
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-[var(--border-custom)]">
          <button
            onClick={logout}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--accent-rose)] transition-all duration-200"
          >
            <LogOut className="w-5 h-5" />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-30 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Main content */}
      <div className="lg:ml-[280px]">
        {/* Top navbar */}
        <header className="sticky top-0 z-20 h-16 bg-[var(--bg-surface)]/80 backdrop-blur-xl border-b border-[var(--border-custom)] flex items-center justify-between px-4 lg:px-8">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(true)}
              className="lg:hidden p-2 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)]"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="hidden md:flex items-center gap-2 text-xs text-[var(--text-secondary)]">
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--accent-emerald)] opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-[var(--accent-emerald)]"></span>
              </span>
              Live System Active
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Search */}
            <div className="relative">
              <button
                onClick={() => setSearchOpen(!searchOpen)}
                className="p-2 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors"
              >
                <Search className="w-5 h-5" />
              </button>
              {searchOpen && (
                <div className="absolute right-0 top-full mt-2 w-72 bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl shadow-xl p-3 animate-fade-in-up">
                  <input
                    autoFocus
                    type="text"
                    placeholder="Search transactions, vehicles..."
                    className="w-full px-3 py-2 bg-[var(--bg-elevated)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:ring-2 focus:ring-[var(--accent-blue)]/30"
                  />
                </div>
              )}
            </div>

            {/* Theme toggle */}
            <button
              onClick={toggleTheme}
              className="p-2 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors"
            >
              {isDark ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
            </button>

            {/* Notifications */}
            <button className="relative p-2 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors">
              <Bell className="w-5 h-5" />
              <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-[var(--accent-rose)] rounded-full" />
            </button>

            {/* Profile */}
            <div className="relative" ref={profileRef}>
              <button
                onClick={() => setProfileOpen(!profileOpen)}
                className="flex items-center gap-2 p-1.5 rounded-xl hover:bg-[var(--bg-elevated)] transition-colors"
              >
                <img
                  src="/avatar.jpg"
                  alt="Profile"
                  className="w-8 h-8 rounded-full object-cover ring-2 ring-[var(--border-custom)]"
                />
                <ChevronDown className="w-4 h-4 text-[var(--text-tertiary)] hidden sm:block" />
              </button>

              {profileOpen && (
                <div className="absolute right-0 top-full mt-2 w-56 bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl shadow-xl py-2 animate-fade-in-up">
                  <div className="px-4 py-3 border-b border-[var(--border-custom)]">
                    <p className="text-sm font-semibold text-[var(--text-primary)]">
                      {user?.full_name || user?.name || 'User'}
                    </p>
                    <p className="text-xs text-[var(--text-secondary)]">{user?.phone}</p>
                    {user?.role && (
                      <span className="inline-block mt-1 text-[10px] bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] px-2 py-0.5 rounded-full capitalize">
                        {user.role}
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => {
                      navigate('/profile');
                      setProfileOpen(false);
                    }}
                    className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] transition-colors"
                  >
                    <User className="w-4 h-4" />
                    Profile
                  </button>
                  <button
                    onClick={() => {
                      toggleTheme();
                      setProfileOpen(false);
                    }}
                    className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] transition-colors"
                  >
                    {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                    {isDark ? 'Light Mode' : 'Dark Mode'}
                  </button>
                  <div className="border-t border-[var(--border-custom)] mt-1 pt-1">
                    <button
                      onClick={() => {
                        logout();
                        setProfileOpen(false);
                      }}
                      className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-[var(--accent-rose)] hover:bg-[var(--bg-elevated)] transition-colors"
                    >
                      <LogOut className="w-4 h-4" />
                      Sign Out
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="p-4 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
