const BASE_URL = (import.meta.env.VITE_API_URL as string) || 'http://localhost:8001/api/v1';

// ─── Auth state helpers (display-only — no tokens stored in JS) ───────────────
export const clearAuthState = () => localStorage.removeItem('auth_user');

// ─── API response wrapper ─────────────────────────────────────────────────────
interface ApiResponse<T = unknown> {
  success: boolean;
  message: string;
  data: T;
  errors?: unknown;
}

export class ApiError extends Error {
  status?: number;
  errors?: Record<string, unknown>;
  constructor(message: string, errors?: Record<string, unknown>, status?: number) {
    super(message);
    this.name = 'ApiError';
    this.errors = errors;
    this.status = status;
  }
}

// ─── Token refresh (called automatically on 401) ──────────────────────────────
let _refreshPromise: Promise<boolean> | null = null;

async function tryRefreshToken(): Promise<boolean> {
  if (_refreshPromise) return _refreshPromise;
  _refreshPromise = fetch(`${BASE_URL}/auth/token/refresh/`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => { _refreshPromise = null; });
  return _refreshPromise;
}

// ─── Core fetch wrapper ───────────────────────────────────────────────────────
// Tokens are httpOnly cookies — browser sends them automatically.
// On 401, we attempt a token refresh once before giving up.
async function apiFetch<T>(endpoint: string, options: RequestInit = {}, isRetry = false): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  const response = await fetch(`${BASE_URL}${endpoint}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (response.status === 401 && !isRetry) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      return apiFetch(endpoint, options, true);
    }
    clearAuthState();
    window.dispatchEvent(new CustomEvent('auth:expired'));
    throw new ApiError('Session expired. Please log in again.', undefined, 401);
  }

  const json: ApiResponse<T> = await response.json();

  if (!response.ok) {
    let message = json.message || `HTTP ${response.status}`;
    const errorsObj = json.errors && typeof json.errors === 'object'
      ? (json.errors as Record<string, unknown>)
      : undefined;
    if (errorsObj) {
      const details = Object.values(errorsObj)
        .flatMap((v) => (Array.isArray(v) ? v : [v]))
        .filter((v) => typeof v === 'string')
        .join(' ');
      if (details) message = `${message}: ${details}`;
    }
    throw new ApiError(message, errorsObj, response.status);
  }

  return json.data as T;
}

// ─── Auth types ───────────────────────────────────────────────────────────────
export interface LoginResponse {
  user_id: number;
  uuid: string;
  full_name: string;
  phone: string;
  role: string;
  // access / refresh tokens are set as httpOnly cookies by the server — not in body
}

export interface MeResponse {
  id: number;
  uuid: string;
  full_name: string;
  phone: string;
  cnic?: string;
  user_role: string;
  status: string;
  created_at: string;
}

// ─── Auth API ─────────────────────────────────────────────────────────────────
export const authApi = {
  login: (data: { phone: string; password: string }) =>
    apiFetch<LoginResponse>('/auth/login/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Cookies cleared server-side — no token body needed
  logout: () =>
    apiFetch<null>('/auth/logout/', { method: 'POST' }),

  me: () => apiFetch<MeResponse>('/auth/me/'),

  updateMe: (data: Partial<{ full_name: string; phone: string }>) =>
    apiFetch<MeResponse>('/auth/me/', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  register: (data: { full_name: string; phone: string; cnic: string; password?: string }) =>
    apiFetch<unknown>('/auth/register/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  changePassword: (data: { old_password: string; new_password: string }) =>
    apiFetch<null>('/auth/change-password/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  adminUsers: (params?: { search?: string; role?: string; status?: string }) => {
    const qs = params
      ? '?' + new URLSearchParams(params as Record<string, string>).toString()
      : '';
    return apiFetch<MeResponse[]>(`/auth/admin/users/${qs}`);
  },

  adminUserDetail: (pk: number) => apiFetch<MeResponse>(`/auth/admin/users/${pk}/`),

  adminUpdateUser: (pk: number, data: Partial<MeResponse>) =>
    apiFetch<MeResponse>(`/auth/admin/users/${pk}/`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
};

// ─── Vehicle types ────────────────────────────────────────────────────────────
export interface ApiVehicle {
  id: string;
  plate_number: string;
  vehicle_type: string;
  status: string;
  registered_at: string;
  owner_phone: string;
  owner_name: string;
  owner_id?: number;
  tag?: {
    id: string;
    tag_serial: string;
    issued_at: string;
    status: string;
    last_scanned_at?: string;
    is_valid: boolean;
  };
}

// ─── Vehicles API ─────────────────────────────────────────────────────────────
export const vehiclesApi = {
  list: (params?: { plate?: string }) => {
    const qs = params?.plate ? `?plate=${encodeURIComponent(params.plate)}` : '';
    return apiFetch<ApiVehicle[]>(`/vehicles/${qs}`);
  },

  create: (data: {
    plate_number: string;
    vehicle_type: string;
    owner_id: number;
    tag_serial: string;
    initial_balance?: number;
  }) => apiFetch<ApiVehicle>('/vehicles/', { method: 'POST', body: JSON.stringify(data) }),

  detail: (uuid: string) => apiFetch<ApiVehicle>(`/vehicles/${uuid}/`),

  update: (uuid: string, data: Partial<ApiVehicle>) =>
    apiFetch<ApiVehicle>(`/vehicles/${uuid}/`, { method: 'PATCH', body: JSON.stringify(data) }),

  byPlate: (plateNumber: string) => apiFetch<ApiVehicle>(`/vehicles/plate/${encodeURIComponent(plateNumber)}/`),

  reissueTag: (vehicleUuid: string, data: { tag_serial: string }) =>
    apiFetch<ApiVehicle['tag']>(`/vehicles/tags/${vehicleUuid}/reissue/`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  addTag: (data: { tag_serial: string; epc?: string }) =>
    apiFetch<{ id: string; tag_serial: string; epc: string }>('/vehicles/tags/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  suspend: (vehicleUuid: string) =>
    apiFetch<ApiVehicle>(`/vehicles/${vehicleUuid}/suspend/`, {
      method: 'POST',
      body: JSON.stringify({ action: 'suspend' }),
    }),

  activate: (vehicleUuid: string) =>
    apiFetch<ApiVehicle>(`/vehicles/${vehicleUuid}/suspend/`, {
      method: 'POST',
      body: JSON.stringify({ action: 'activate' }),
    }),

  availableTags: (params?: { search?: string }) => {
    const qs = params?.search ? `?search=${encodeURIComponent(params.search)}` : '';
    return apiFetch<{ id: string; tag_serial: string; epc: string }[]>(`/vehicles/tags/available/${qs}`);
  },

  uploadTagInventory: async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${BASE_URL}/vehicles/tags/upload/`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    });
    const json = await res.json();
    if (!res.ok) throw new ApiError(json.message || `HTTP ${res.status}`);
    return json.data as { added: number; skipped: number; errors: string[]; skipped_serials: string[] };
  },
};

// ─── Toll types ───────────────────────────────────────────────────────────────
export interface Lane {
  id: string;
  lane_number: number;
  is_active: boolean;
}

export interface Plaza {
  id: string;
  name: string;
  code: string;
  latitude?: string;
  longitude?: string;
  is_active: boolean;
  lanes: Lane[];
}

export interface TollRate {
  id: string;
  entry_plaza: string;
  entry_plaza_name: string;
  exit_plaza: string;
  exit_plaza_name: string;
  vehicle_type: string;
  rate: string;
  effective_from: string;
}

export interface TollTrip {
  id: string;
  plate_number: string;
  entry_plaza_name: string;
  exit_plaza_name?: string;
  entry_time: string;
  exit_time?: string;
  charge_amount?: string;
  balance_before?: string;
  balance_after?: string;
  status: string;
  duration_minutes?: number;
}

export interface StatsData {
  monthly: { month: string; toll: number; transactions: number }[];
  daily: { day: string; amount: number; count: number }[];
  vehicle_type_breakdown: { name: string; value: number; count: number }[];
  plaza_stats: { name: string; revenue: number; trips: number; is_active: boolean }[];
  total_vehicles: number;
  total_balance: number;
  active_plazas: number;
  total_trips: number;
  completed_trips: number;
  active_trips: number;
  total_revenue: number;
}

// ─── Tolls API ────────────────────────────────────────────────────────────────
export const tollsApi = {
  entry: (data: { tag_serial: string; plaza_id: string; lane_id?: string }) =>
    apiFetch<TollTrip>('/tolls/entry/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  exit: (data: { tag_serial: string; plaza_id: string; lane_id?: string }) =>
    apiFetch<TollTrip>('/tolls/exit/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  plazas: () => apiFetch<Plaza[]>('/tolls/plazas/'),

  rates: () => apiFetch<TollRate[]>('/tolls/rates/'),

  trips: (vehicleUuid: string) => apiFetch<TollTrip[]>(`/tolls/trips/${vehicleUuid}/`),

  adminTrips: (params?: { status?: string }) => {
    const qs = params?.status ? `?status=${params.status}` : '';
    return apiFetch<TollTrip[]>(`/tolls/admin/trips/${qs}`);
  },

  adminPlazas: () => apiFetch<Plaza[]>('/tolls/admin/plazas/'),

  adminCreatePlaza: (data: { name: string; code: string; latitude?: string; longitude?: string; is_active?: boolean }) =>
    apiFetch<Plaza>('/tolls/admin/plazas/', { method: 'POST', body: JSON.stringify(data) }),

  adminUpdatePlaza: (id: string, data: { is_active?: boolean; name?: string }) =>
    apiFetch<Plaza>(`/tolls/admin/plazas/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),

  adminCreateLane: (plazaId: string, data: { lane_number: number; is_active?: boolean }) =>
    apiFetch<Lane>(`/tolls/admin/plazas/${plazaId}/lanes/`, { method: 'POST', body: JSON.stringify(data) }),

  adminCreateRate: (data: {
    entry_plaza: string;
    exit_plaza: string;
    vehicle_type: string;
    rate: string;
    effective_from: string;
  }) => apiFetch<TollRate>('/tolls/admin/rates/', { method: 'POST', body: JSON.stringify(data) }),

  adminDeleteRate: (id: string) =>
    apiFetch<null>(`/tolls/admin/rates/${id}/`, { method: 'DELETE' }),

  adminDeletePlaza: (id: string) =>
    apiFetch<null>(`/tolls/admin/plazas/${id}/`, { method: 'DELETE' }),

  stats: () => apiFetch<StatsData>('/tolls/admin/stats/'),

  closeTrip: (tripId: string) =>
    apiFetch<TollTrip>(`/tolls/admin/trips/${tripId}/close/`, { method: 'POST' }),

  refundTrip: (tripId: string) =>
    apiFetch<{ trip_id: string; plate_number: string; refunded_amount: string; new_balance: string }>(
      `/tolls/admin/trips/${tripId}/refund/`, { method: 'POST' }
    ),

  gateEvents: (params?: { pending?: boolean }) => {
    const qs = params?.pending ? '?pending=1' : '';
    return apiFetch<{ id: number; plaza: string; lane: number | null; created_at: string; executed_at: string | null; status: string }[]>(
      `/tolls/admin/gate-events/${qs}`
    );
  },
};

// ─── Account types ────────────────────────────────────────────────────────────
export interface Account {
  id: string;
  plate_number: string;
  vehicle_type: string;
  balance: string;
  balance_updated_at: string;
  created_at: string;
}

export interface ApiTransaction {
  id: string;
  transaction_type: string;
  amount: string;
  balance_before: string;
  balance_after: string;
  status: string;
  tag_serial?: string;
  processed_at: string;
  description?: string;
}

export interface TransferResult {
  transferred_amount: string;
  source_vehicle: string;
  target_vehicle: string;
  reference_id: string;
}

// ─── Accounts API ─────────────────────────────────────────────────────────────
export const accountsApi = {
  byVehicle: (vehicleUuid: string) => apiFetch<Account>(`/accounts/vehicle/${vehicleUuid}/`),

  transactions: (accountUuid: string, params?: { type?: string; page?: number }) => {
    const qs = params
      ? '?' + new URLSearchParams(params as Record<string, string>).toString()
      : '';
    return apiFetch<{ results: ApiTransaction[]; count: number; next?: string; previous?: string }>(
      `/accounts/${accountUuid}/transactions/${qs}`
    );
  },

  adminAll: () => apiFetch<Account[]>('/accounts/admin/all/'),

  operatorTopup: (tag_serial: string, amount: number) =>
    apiFetch<{ plate_number: string; amount_added: string; new_balance: string }>(
      '/accounts/operator/topup/',
      { method: 'POST', body: JSON.stringify({ tag_serial, amount }) }
    ),

  plateTopup: (plate_number: string, amount: number) =>
    apiFetch<{ plate_number: string; vehicle_type: string; amount_added: string; balance_before: string; new_balance: string }>(
      '/accounts/topup/plate/',
      { method: 'POST', body: JSON.stringify({ plate_number, amount }) }
    ),

  transferBalance: (data: {
    source_vehicle_id: string;
    target_vehicle_id: string;
    cnic: string;
    phone: string;
    name: string;
  }) =>
    apiFetch<TransferResult>('/accounts/transfer/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

// ─── Payment types ────────────────────────────────────────────────────────────
export interface TopupRequest {
  id: string;
  amount: string;
  status: string;
  jazzcash_txn_id?: string;
  requested_at: string;
  completed_at?: string;
}

// ─── Payments API ─────────────────────────────────────────────────────────────
export const paymentsApi = {
  initiate: (data: { account_id: string; amount: number }) =>
    apiFetch<TopupRequest>('/payments/topup/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  callback: (data: { pp_TxnRefNo: string; pp_ResponseCode: string; topup_id: string }) =>
    apiFetch<TopupRequest>('/payments/jazzcash/callback/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  history: (accountUuid: string) =>
    apiFetch<TopupRequest[]>(`/payments/history/${accountUuid}/`),
};
