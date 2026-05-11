import { useState, useEffect } from 'react';
import { useToast } from '@/context/ToastContext';
import { useAuth } from '@/context/AuthContext';
import { vehiclesApi } from '@/services/api';
import { normalizePlate } from '@/lib/plate';
import type { ApiVehicle } from '@/types';
import {
  Search,
  Plus,
  Pencil,
  Car,
  Truck,
  Bus,
  Bike,
  X,
  CheckCircle,
  Loader2,
  Filter,
  RefreshCw,
  Tag,
  Upload,
  AlertTriangle,
  ShieldOff,
  ShieldCheck,
} from 'lucide-react';

const PAGE_SIZE = 12;

const vehicleIcons: Record<string, React.ElementType> = {
  car: Car,
  truck: Truck,
  bus: Bus,
  motorcycle: Bike,
};

const getVehicleIcon = (type: string) => vehicleIcons[type?.toLowerCase()] || Car;

export default function Vehicles() {
  const { addToast } = useToast();
  const { user } = useAuth();

  const [vehicles, setVehicles] = useState<ApiVehicle[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [showModal, setShowModal] = useState(false);
  const [editingVehicle, setEditingVehicle] = useState<ApiVehicle | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showFilters, setShowFilters] = useState(false);

  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{ added: number; skipped: number; errors: string[]; skipped_serials: string[] } | null>(null);

  // Single tag add
  const [showAddTagModal, setShowAddTagModal] = useState(false);
  const [addTagForm, setAddTagForm] = useState({ tag_serial: '', epc: '' });
  const [isAddingTag, setIsAddingTag] = useState(false);

  // Suspend/activate
  const [suspendTarget, setSuspendTarget] = useState<ApiVehicle | null>(null);
  const [isSuspending, setIsSuspending] = useState(false);

  // Pagination
  const [currentPage, setCurrentPage] = useState(1);

  const [reissueVehicle, setReissueVehicle] = useState<ApiVehicle | null>(null);
  const [reissueForm, setReissueForm] = useState({ tag_serial: '' });
  const [isReissuing, setIsReissuing] = useState(false);
  const [reissueTags, setReissueTags] = useState<{ id: string; tag_serial: string; epc: string }[]>([]);
  const [reissueTagsLoading, setReissueTagsLoading] = useState(false);
  const [showReissueConfirm, setShowReissueConfirm] = useState(false);

  const [form, setForm] = useState({
    plate_number: '',
    vehicle_type: 'car',
    owner_id: '',
    tag_serial: '',
    status: 'active',
  });

  const fetchVehicles = async (plate?: string) => {
    setLoading(true);
    try {
      const data = await vehiclesApi.list(plate ? { plate } : undefined);
      setVehicles(data as ApiVehicle[]);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load vehicles';
      addToast({ type: 'error', title: 'Error', message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchVehicles();
  }, []);

  const handleAddTag = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addTagForm.tag_serial.trim()) {
      addToast({ type: 'error', title: 'Required', message: 'Tag serial is required.' });
      return;
    }
    setIsAddingTag(true);
    try {
      await vehiclesApi.addTag({ tag_serial: addTagForm.tag_serial.trim(), epc: addTagForm.epc.trim() });
      addToast({ type: 'success', title: 'Tag Added', message: `${addTagForm.tag_serial} added to inventory.` });
      setShowAddTagModal(false);
      setAddTagForm({ tag_serial: '', epc: '' });
    } catch (err: unknown) {
      addToast({ type: 'error', title: 'Failed', message: err instanceof Error ? err.message : 'Could not add tag' });
    } finally {
      setIsAddingTag(false);
    }
  };

  const handleSuspendToggle = async () => {
    if (!suspendTarget) return;
    setIsSuspending(true);
    const isSuspended = suspendTarget.status === 'suspended';
    try {
      const updated = isSuspended
        ? await vehiclesApi.activate(suspendTarget.id)
        : await vehiclesApi.suspend(suspendTarget.id);
      setVehicles((prev) => prev.map((v) => (v.id === updated.id ? { ...v, ...updated } : v)));
      addToast({ type: 'success', title: isSuspended ? 'Activated' : 'Suspended', message: `${suspendTarget.plate_number} has been ${isSuspended ? 'activated' : 'suspended'}.` });
      setSuspendTarget(null);
    } catch (err: unknown) {
      addToast({ type: 'error', title: 'Failed', message: err instanceof Error ? err.message : 'Operation failed' });
    } finally {
      setIsSuspending(false);
    }
  };

  const filteredVehicles = vehicles.filter((v) => {
    const s = search.toLowerCase();
    const matchesSearch =
      v.plate_number.toLowerCase().includes(s) ||
      v.owner_name?.toLowerCase().includes(s) ||
      v.owner_phone?.toLowerCase().includes(s) ||
      v.tag?.tag_serial?.toLowerCase().includes(s);
    const matchesType = typeFilter === 'All' || v.vehicle_type.toLowerCase() === typeFilter.toLowerCase();
    const matchesStatus = statusFilter === 'All' || v.status.toLowerCase() === statusFilter.toLowerCase();
    return matchesSearch && matchesType && matchesStatus;
  });

  const totalPages = Math.ceil(filteredVehicles.length / PAGE_SIZE);
  const pagedVehicles = filteredVehicles.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const openAdd = () => {
    setEditingVehicle(null);
    setForm({
      plate_number: '',
      vehicle_type: 'car',
      owner_id: user?.id?.toString() || '',
      tag_serial: '',
      status: 'active',
    });
    setShowModal(true);
  };

  const openEdit = (vehicle: ApiVehicle) => {
    setEditingVehicle(vehicle);
    setForm({
      plate_number: vehicle.plate_number,
      vehicle_type: vehicle.vehicle_type,
      owner_id: vehicle.owner_id?.toString() || '',
      tag_serial: vehicle.tag?.tag_serial || '',
      status: vehicle.status,
    });
    setShowModal(true);
  };

  const handleUpload = async () => {
    if (!uploadFile) return;
    setIsUploading(true);
    setUploadResult(null);
    try {
      const result = await vehiclesApi.uploadTagInventory(uploadFile);
      setUploadResult(result);
      addToast({ type: 'success', title: 'Upload Complete', message: `${result.added} tag(s) added, ${result.skipped} skipped.` });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Upload failed';
      addToast({ type: 'error', title: 'Upload Failed', message });
    } finally {
      setIsUploading(false);
    }
  };

  const openReissue = async (vehicle: ApiVehicle) => {
    setReissueVehicle(vehicle);
    setReissueForm({ tag_serial: '' });
    setShowReissueConfirm(false);
    setReissueTagsLoading(true);
    try {
      const tags = await vehiclesApi.availableTags();
      setReissueTags(tags);
    } catch {
      addToast({ type: 'error', title: 'Error', message: 'Failed to load available tags.' });
    } finally {
      setReissueTagsLoading(false);
    }
  };

  const handleReissueConfirm = async () => {
    if (!reissueVehicle || !reissueForm.tag_serial) return;
    setIsReissuing(true);
    try {
      await vehiclesApi.reissueTag(reissueVehicle.id, { tag_serial: reissueForm.tag_serial });
      addToast({ type: 'success', title: 'Tag Reissued', message: 'New tag assigned. Previous tag permanently deactivated.' });
      setReissueVehicle(null);
      setReissueForm({ tag_serial: '' });
      setShowReissueConfirm(false);
      fetchVehicles();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Reissue failed';
      addToast({ type: 'error', title: 'Reissue Failed', message });
    } finally {
      setIsReissuing(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingVehicle && (!form.plate_number || !form.tag_serial)) {
      addToast({ type: 'error', title: 'Validation Error', message: 'Please fill all required fields.' });
      return;
    }
    if (!editingVehicle && !form.owner_id) {
      addToast({ type: 'error', title: 'Validation Error', message: 'Owner ID is required.' });
      return;
    }

    setIsSubmitting(true);
    try {
      if (editingVehicle) {
        await vehiclesApi.update(editingVehicle.id, { status: form.status });
        addToast({ type: 'success', title: 'Vehicle Updated', message: 'Vehicle status updated successfully.' });
      } else {
        await vehiclesApi.create({
          plate_number: form.plate_number,
          vehicle_type: form.vehicle_type,
          owner_id: parseInt(form.owner_id),
          tag_serial: form.tag_serial,
        });
        addToast({ type: 'success', title: 'Vehicle Added', message: 'New vehicle registered successfully.' });
      }
      setShowModal(false);
      fetchVehicles();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Operation failed';
      addToast({ type: 'error', title: 'Error', message });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="animate-fade-in-up">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Vehicle Management</h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            {vehicles.length} vehicles registered in the system
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => fetchVehicles()}
            className="flex items-center gap-2 px-4 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-secondary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors self-start"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
          {user?.role === 'admin' && (
            <>
              <button
                onClick={() => { setShowAddTagModal(true); setAddTagForm({ tag_serial: '', epc: '' }); }}
                className="flex items-center gap-2 px-4 py-2.5 bg-[var(--accent-cyan)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity self-start"
              >
                <Tag className="w-4 h-4" />
                Add Tag
              </button>
              <button
                onClick={() => { setShowUploadModal(true); setUploadFile(null); setUploadResult(null); }}
                className="flex items-center gap-2 px-4 py-2.5 bg-[var(--accent-emerald)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity self-start"
              >
                <Upload className="w-4 h-4" />
                Upload Tags
              </button>
            </>
          )}
          <button
            onClick={openAdd}
            className="flex items-center gap-2 px-4 py-2.5 bg-[var(--accent-blue)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity self-start"
          >
            <Plus className="w-4 h-4" />
            Add Vehicle
          </button>
        </div>
      </div>

      {/* Search & Filters */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-4 mb-6 shadow-sm">
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-tertiary)]" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by plate, owner, tag serial..."
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
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="px-3 py-2 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-lg text-sm text-[var(--text-primary)] outline-none"
            >
              <option value="All">All Types</option>
              <option value="car">Car</option>
              <option value="truck">Truck</option>
              <option value="bus">Bus</option>
              <option value="motorcycle">Motorcycle</option>
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-lg text-sm text-[var(--text-primary)] outline-none"
            >
              <option value="All">All Status</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="suspended">Suspended</option>
            </select>
            <button
              onClick={() => {
                setTypeFilter('All');
                setStatusFilter('All');
                setSearch('');
              }}
              className="px-3 py-2 text-sm text-[var(--accent-rose)] hover:bg-[var(--accent-rose)]/10 rounded-lg transition-colors"
            >
              Clear Filters
            </button>
          </div>
        )}
      </div>

      {/* Loading */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-[var(--accent-blue)]" />
        </div>
      ) : filteredVehicles.length === 0 ? (
        <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-12 text-center shadow-sm">
          <Car className="w-12 h-12 text-[var(--text-tertiary)] mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">No vehicles found</h3>
          <p className="text-sm text-[var(--text-secondary)]">
            Try adjusting your search or filters, or add a new vehicle.
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {pagedVehicles.map((vehicle) => {
              const Icon = getVehicleIcon(vehicle.vehicle_type);
              const isSuspended = vehicle.status === 'suspended';
              const statusColor =
                vehicle.status === 'active'
                  ? 'bg-[var(--accent-emerald)]/10 text-[var(--accent-emerald)] border-[var(--accent-emerald)]/20'
                  : vehicle.status === 'suspended'
                  ? 'bg-[var(--accent-amber)]/10 text-[var(--accent-amber)] border-[var(--accent-amber)]/20'
                  : 'bg-[var(--accent-rose)]/10 text-[var(--accent-rose)] border-[var(--accent-rose)]/20';
              const iconColor =
                vehicle.status === 'active' ? 'text-[var(--accent-emerald)]' : 'text-[var(--accent-rose)]';
              const iconBg =
                vehicle.status === 'active' ? 'bg-[var(--accent-emerald)]/10' : 'bg-[var(--accent-rose)]/10';
              return (
                <div
                  key={vehicle.id}
                  className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-xl p-5 shadow-sm hover:shadow-md hover:border-[var(--accent-blue)]/20 transition-all duration-200"
                >
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <div className={`p-2.5 rounded-lg ${iconBg}`}>
                        <Icon className={`w-5 h-5 ${iconColor}`} />
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-[var(--text-primary)]">{vehicle.plate_number}</h3>
                        <p className="text-xs text-[var(--text-secondary)] capitalize">{vehicle.vehicle_type}</p>
                      </div>
                    </div>
                    <span className={`px-2.5 py-1 rounded-full text-xs font-medium border capitalize ${statusColor}`}>
                      {vehicle.status}
                    </span>
                  </div>

                  <div className="space-y-2 mb-4">
                    <div className="flex justify-between text-sm">
                      <span className="text-[var(--text-secondary)]">Owner</span>
                      <span className="text-[var(--text-primary)] font-medium">{vehicle.owner_name || '—'}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-[var(--text-secondary)]">M-Tag Serial</span>
                      <span className="text-[var(--text-primary)] font-mono text-xs">{vehicle.tag?.tag_serial || '—'}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-[var(--text-secondary)]">Tag Valid</span>
                      <span className={`text-xs font-medium ${vehicle.tag?.is_valid ? 'text-[var(--accent-emerald)]' : 'text-[var(--accent-rose)]'}`}>
                        {vehicle.tag ? (vehicle.tag.is_valid ? 'Valid' : 'Expired/Suspended') : 'No Tag'}
                      </span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-[var(--text-secondary)]">Registered</span>
                      <span className="text-[var(--text-primary)]">
                        {vehicle.registered_at ? new Date(vehicle.registered_at).toLocaleDateString('en-PK') : '—'}
                      </span>
                    </div>
                  </div>

                  <div className="flex gap-2 pt-3 border-t border-[var(--border-custom)]">
                    {user?.role === 'admin' && (
                      <button
                        onClick={() => setSuspendTarget(vehicle)}
                        className={`flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-xs font-medium border transition-colors ${
                          isSuspended
                            ? 'text-[var(--accent-emerald)] border-[var(--accent-emerald)]/30 hover:bg-[var(--accent-emerald)]/10'
                            : 'text-[var(--accent-amber)] border-[var(--accent-amber)]/30 hover:bg-[var(--accent-amber)]/10'
                        }`}
                      >
                        {isSuspended ? <ShieldCheck className="w-3.5 h-3.5" /> : <ShieldOff className="w-3.5 h-3.5" />}
                        {isSuspended ? 'Activate' : 'Suspend'}
                      </button>
                    )}
                    <button
                      onClick={() => openReissue(vehicle)}
                      className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-lg text-sm text-[var(--text-secondary)] hover:text-[var(--accent-amber)] hover:border-[var(--accent-amber)]/30 transition-colors"
                    >
                      <Tag className="w-3.5 h-3.5" />
                      Reissue Tag
                    </button>
                    <button
                      onClick={() => openEdit(vehicle)}
                      className="flex items-center justify-center gap-1.5 py-2 px-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-lg text-sm text-[var(--text-secondary)] hover:text-[var(--accent-blue)] hover:border-[var(--accent-blue)]/30 transition-colors"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-6">
              <p className="text-sm text-[var(--text-secondary)]">
                Showing {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filteredVehicles.length)} of {filteredVehicles.length} vehicles
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className="px-4 py-2 bg-[var(--bg-surface)] border border-[var(--border-custom)] text-sm text-[var(--text-secondary)] rounded-xl hover:bg-[var(--bg-elevated)] transition-colors disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages}
                  className="px-4 py-2 bg-[var(--bg-surface)] border border-[var(--border-custom)] text-sm text-[var(--text-secondary)] rounded-xl hover:bg-[var(--bg-elevated)] transition-colors disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Reissue Tag Modal */}
      {reissueVehicle && !showReissueConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-fade-in-up">
          <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-2xl shadow-2xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-custom)]">
              <h2 className="text-lg font-semibold text-[var(--text-primary)]">Reissue Tag</h2>
              <button
                onClick={() => setReissueVehicle(null)}
                className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-tertiary)] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-sm text-[var(--text-secondary)]">
                Replacing tag for <span className="font-mono font-semibold text-[var(--text-primary)]">{reissueVehicle.plate_number}</span>.
                The current tag will be permanently deactivated.
              </p>
              <div>
                <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                  Select New Tag <span className="text-[var(--accent-rose)]">*</span>
                </label>
                {reissueTagsLoading ? (
                  <div className="flex items-center gap-2 px-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-tertiary)]">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Loading available tags…
                  </div>
                ) : (
                  <select
                    value={reissueForm.tag_serial}
                    onChange={(e) => setReissueForm({ tag_serial: e.target.value })}
                    className="w-full px-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-amber)] focus:ring-2 focus:ring-[var(--accent-amber)]/20 transition-all"
                  >
                    <option value="">— Select an unassigned tag —</option>
                    {reissueTags.map((t) => (
                      <option key={t.id} value={t.tag_serial}>
                        {t.tag_serial}
                      </option>
                    ))}
                  </select>
                )}
                {!reissueTagsLoading && reissueTags.length === 0 && (
                  <p className="text-xs text-[var(--text-tertiary)] mt-1">No unassigned tags in inventory.</p>
                )}
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setReissueVehicle(null)}
                  className="flex-1 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-primary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={!reissueForm.tag_serial}
                  onClick={() => setShowReissueConfirm(true)}
                  className="flex-1 py-2.5 bg-[var(--accent-amber)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  <Tag className="w-4 h-4" />
                  Reissue
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Reissue Confirm Modal */}
      {reissueVehicle && showReissueConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-fade-in-up">
          <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-2xl shadow-2xl w-full max-w-sm">
            <div className="p-6 text-center space-y-4">
              <div className="w-14 h-14 bg-[var(--accent-amber)]/10 rounded-full flex items-center justify-center mx-auto">
                <Tag className="w-7 h-7 text-[var(--accent-amber)]" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-[var(--text-primary)] mb-1">Confirm Tag Reissue</h2>
                <p className="text-sm text-[var(--text-secondary)]">
                  Once this tag is reissued, the previous tag will be permanently disabled and cannot be assigned again.
                </p>
              </div>
              <div className="bg-[var(--bg-elevated)] rounded-xl p-3 text-left space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">Vehicle</span>
                  <span className="font-mono font-semibold text-[var(--text-primary)]">{reissueVehicle.plate_number}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">Current tag</span>
                  <span className="font-mono text-xs text-[var(--accent-rose)]">{reissueVehicle.tag?.tag_serial || '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">New tag</span>
                  <span className="font-mono text-xs text-[var(--accent-emerald)]">{reissueForm.tag_serial}</span>
                </div>
              </div>
              <p className="text-xs text-[var(--text-tertiary)]">Are you sure you want to continue?</p>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setShowReissueConfirm(false)}
                  className="flex-1 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-primary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors"
                >
                  Go Back
                </button>
                <button
                  type="button"
                  disabled={isReissuing}
                  onClick={handleReissueConfirm}
                  className="flex-1 py-2.5 bg-[var(--accent-amber)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {isReissuing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  Yes, Reissue
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Upload Tags Modal */}
      {showUploadModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-fade-in-up">
          <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-2xl shadow-2xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-custom)]">
              <h2 className="text-lg font-semibold text-[var(--text-primary)]">Upload Tag Inventory</h2>
              <button
                onClick={() => setShowUploadModal(false)}
                className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-tertiary)] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <p className="text-sm text-[var(--text-secondary)]">
                Upload a CSV file exported from the RFID scanner. Columns required: <span className="font-mono text-xs bg-[var(--bg-elevated)] px-1.5 py-0.5 rounded">TID</span> and <span className="font-mono text-xs bg-[var(--bg-elevated)] px-1.5 py-0.5 rounded">EPC</span>. Tags that already exist will be skipped automatically.
              </p>

              {/* File picker */}
              <label className={`flex flex-col items-center justify-center gap-3 w-full h-32 border-2 border-dashed rounded-xl cursor-pointer transition-colors ${
                uploadFile
                  ? 'border-[var(--accent-emerald)] bg-[var(--accent-emerald)]/5'
                  : 'border-[var(--border-custom)] hover:border-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/5'
              }`}>
                <input
                  type="file"
                  accept=".csv"
                  className="hidden"
                  onChange={(e) => { setUploadFile(e.target.files?.[0] || null); setUploadResult(null); }}
                />
                {uploadFile ? (
                  <>
                    <CheckCircle className="w-6 h-6 text-[var(--accent-emerald)]" />
                    <span className="text-sm font-medium text-[var(--text-primary)]">{uploadFile.name}</span>
                    <span className="text-xs text-[var(--text-tertiary)]">{(uploadFile.size / 1024).toFixed(1)} KB — click to change</span>
                  </>
                ) : (
                  <>
                    <Upload className="w-6 h-6 text-[var(--text-tertiary)]" />
                    <span className="text-sm text-[var(--text-secondary)]">Click to browse CSV file</span>
                  </>
                )}
              </label>

              {/* Result */}
              {uploadResult && (
                <div className="space-y-2">
                  <div className="flex gap-3">
                    <div className="flex-1 bg-[var(--accent-emerald)]/10 border border-[var(--accent-emerald)]/20 rounded-xl p-3 text-center">
                      <p className="text-2xl font-bold text-[var(--accent-emerald)]">{uploadResult.added}</p>
                      <p className="text-xs text-[var(--text-secondary)] mt-0.5">Added</p>
                    </div>
                    <div className="flex-1 bg-[var(--accent-amber)]/10 border border-[var(--accent-amber)]/20 rounded-xl p-3 text-center">
                      <p className="text-2xl font-bold text-[var(--accent-amber)]">{uploadResult.skipped}</p>
                      <p className="text-xs text-[var(--text-secondary)] mt-0.5">Already Existed</p>
                    </div>
                  </div>
                  {uploadResult.errors.length > 0 && (
                    <div className="flex items-start gap-2 px-3 py-2 bg-[var(--accent-rose)]/10 border border-[var(--accent-rose)]/20 rounded-lg text-xs text-[var(--accent-rose)]">
                      <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                      <span>{uploadResult.errors.join(', ')}</span>
                    </div>
                  )}
                </div>
              )}

              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={() => setShowUploadModal(false)}
                  className="flex-1 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-primary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors"
                >
                  {uploadResult ? 'Close' : 'Cancel'}
                </button>
                {!uploadResult && (
                  <button
                    type="button"
                    disabled={!uploadFile || isUploading}
                    onClick={handleUpload}
                    className="flex-1 py-2.5 bg-[var(--accent-emerald)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    {isUploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                    {isUploading ? 'Uploading…' : 'Upload'}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-fade-in-up">
          <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-custom)]">
              <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                {editingVehicle ? 'Edit Vehicle' : 'Add Vehicle'}
              </h2>
              <button
                onClick={() => setShowModal(false)}
                className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-tertiary)] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-5">
              {!editingVehicle && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                      Plate Number <span className="text-[var(--accent-rose)]">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.plate_number}
                      onChange={(e) => setForm((p) => ({ ...p, plate_number: normalizePlate(e.target.value) }))}
                      placeholder="LHR1234"
                      className="w-full px-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--accent-blue)] focus:ring-2 focus:ring-[var(--accent-blue)]/20 transition-all"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                        Vehicle Type <span className="text-[var(--accent-rose)]">*</span>
                      </label>
                      <select
                        value={form.vehicle_type}
                        onChange={(e) => setForm((p) => ({ ...p, vehicle_type: e.target.value }))}
                        className="w-full px-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-blue)] focus:ring-2 focus:ring-[var(--accent-blue)]/20 transition-all"
                      >
                        <option value="car">Car</option>
                        <option value="truck">Truck</option>
                        <option value="bus">Bus</option>
                        <option value="motorcycle">Motorcycle</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                        Owner ID <span className="text-[var(--accent-rose)]">*</span>
                      </label>
                      <input
                        type="number"
                        value={form.owner_id}
                        onChange={(e) => setForm((p) => ({ ...p, owner_id: e.target.value }))}
                        placeholder="User ID"
                        className="w-full px-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--accent-blue)] focus:ring-2 focus:ring-[var(--accent-blue)]/20 transition-all"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                      Tag Serial <span className="text-[var(--accent-rose)]">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.tag_serial}
                      onChange={(e) => setForm((p) => ({ ...p, tag_serial: e.target.value }))}
                      placeholder="MTAG-XXXXXXXX"
                      className="w-full px-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--accent-blue)] focus:ring-2 focus:ring-[var(--accent-blue)]/20 transition-all"
                    />
                  </div>
                </>
              )}

              {editingVehicle && (
                <div>
                  <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                    Status
                  </label>
                  <select
                    value={form.status}
                    onChange={(e) => setForm((p) => ({ ...p, status: e.target.value }))}
                    className="w-full px-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-blue)] focus:ring-2 focus:ring-[var(--accent-blue)]/20 transition-all"
                  >
                    <option value="active">Active</option>
                    <option value="inactive">Inactive</option>
                  </select>
                  <p className="text-xs text-[var(--text-tertiary)] mt-2">
                    Editing vehicle: <span className="font-mono font-medium">{editingVehicle.plate_number}</span>
                  </p>
                </div>
              )}

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="flex-1 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-primary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex-1 py-2.5 bg-[var(--accent-blue)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Saving...
                    </>
                  ) : editingVehicle ? (
                    <>
                      <CheckCircle className="w-4 h-4" />
                      Update
                    </>
                  ) : (
                    <>
                      <Plus className="w-4 h-4" />
                      Add Vehicle
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add Tag Modal */}
      {showAddTagModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-fade-in-up">
          <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-2xl shadow-2xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-custom)]">
              <h2 className="text-lg font-semibold text-[var(--text-primary)]">Add Tag to Inventory</h2>
              <button
                onClick={() => setShowAddTagModal(false)}
                className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-tertiary)] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleAddTag} className="p-6 space-y-4">
              <p className="text-sm text-[var(--text-secondary)]">
                Add a single RFID tag to the unassigned inventory. It can then be assigned to a vehicle during registration or reissue.
              </p>
              <div>
                <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                  Tag Serial <span className="text-[var(--accent-rose)]">*</span>
                </label>
                <input
                  type="text"
                  value={addTagForm.tag_serial}
                  onChange={(e) => setAddTagForm((p) => ({ ...p, tag_serial: e.target.value }))}
                  placeholder="MTAG-XXXXXXXX"
                  className="w-full px-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--accent-cyan)] focus:ring-2 focus:ring-[var(--accent-cyan)]/20 transition-all font-mono"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                  EPC <span className="text-[var(--text-tertiary)] text-xs font-normal">(optional)</span>
                </label>
                <input
                  type="text"
                  value={addTagForm.epc}
                  onChange={(e) => setAddTagForm((p) => ({ ...p, epc: e.target.value }))}
                  placeholder="Electronic Product Code"
                  className="w-full px-4 py-3 bg-[var(--bg-elevated)] border border-[var(--border-custom)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none focus:border-[var(--accent-cyan)] focus:ring-2 focus:ring-[var(--accent-cyan)]/20 transition-all font-mono"
                />
              </div>
              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={() => setShowAddTagModal(false)}
                  className="flex-1 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-primary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isAddingTag}
                  className="flex-1 py-2.5 bg-[var(--accent-cyan)] text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {isAddingTag ? <Loader2 className="w-4 h-4 animate-spin" /> : <Tag className="w-4 h-4" />}
                  {isAddingTag ? 'Adding…' : 'Add Tag'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Suspend / Activate Confirmation Modal */}
      {suspendTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-fade-in-up">
          <div className="bg-[var(--bg-surface)] border border-[var(--border-custom)] rounded-2xl shadow-2xl w-full max-w-sm">
            <div className="p-6 text-center space-y-4">
              <div className={`w-14 h-14 rounded-full flex items-center justify-center mx-auto ${
                suspendTarget.status === 'suspended'
                  ? 'bg-[var(--accent-emerald)]/10'
                  : 'bg-[var(--accent-amber)]/10'
              }`}>
                {suspendTarget.status === 'suspended'
                  ? <ShieldCheck className="w-7 h-7 text-[var(--accent-emerald)]" />
                  : <ShieldOff className="w-7 h-7 text-[var(--accent-amber)]" />
                }
              </div>
              <div>
                <h2 className="text-lg font-bold text-[var(--text-primary)] mb-1">
                  {suspendTarget.status === 'suspended' ? 'Activate Vehicle?' : 'Suspend Vehicle?'}
                </h2>
                <p className="text-sm text-[var(--text-secondary)]">
                  {suspendTarget.status === 'suspended'
                    ? 'The vehicle and its M-Tag will be re-enabled. It will be able to pass through toll plazas again.'
                    : 'The vehicle and its M-Tag will be blocked. It will be denied entry at all toll plazas until reactivated.'}
                </p>
              </div>
              <div className="bg-[var(--bg-elevated)] rounded-xl p-3 text-left space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">Plate</span>
                  <span className="font-mono font-semibold text-[var(--text-primary)]">{suspendTarget.plate_number}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">M-Tag</span>
                  <span className="font-mono text-xs text-[var(--text-primary)]">{suspendTarget.tag?.tag_serial || '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">Current Status</span>
                  <span className={`text-xs font-medium capitalize ${
                    suspendTarget.status === 'active' ? 'text-[var(--accent-emerald)]' : 'text-[var(--accent-amber)]'
                  }`}>{suspendTarget.status}</span>
                </div>
              </div>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setSuspendTarget(null)}
                  disabled={isSuspending}
                  className="flex-1 py-2.5 bg-[var(--bg-elevated)] border border-[var(--border-custom)] text-[var(--text-primary)] text-sm font-medium rounded-xl hover:bg-[var(--bg-surface)] transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={isSuspending}
                  onClick={handleSuspendToggle}
                  className={`flex-1 py-2.5 text-white text-sm font-medium rounded-xl hover:opacity-90 transition-opacity disabled:opacity-60 flex items-center justify-center gap-2 ${
                    suspendTarget.status === 'suspended' ? 'bg-[var(--accent-emerald)]' : 'bg-[var(--accent-amber)]'
                  }`}
                >
                  {isSuspending ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {isSuspending
                    ? 'Processing…'
                    : suspendTarget.status === 'suspended'
                    ? 'Yes, Activate'
                    : 'Yes, Suspend'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
