# m-tag Toll System — Complete Architecture

## Network Layout

```
┌─────────────────────────────────────────────────────────┐
│                    MALIR EXPRESSWAY                      │
│                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │ Plaza A  │    │ Plaza B  │    │ Plaza C  │          │
│  │  Gate PC │    │  Gate PC │    │  Gate PC │          │
│  └──────────┘    └──────────┘    └──────────┘          │
│       │               │               │                  │
│       └───────────────┴───────────────┘                  │
│                       │                                  │
│               LAN (192.168.x.x)                         │
│                       │                                  │
│              ┌────────────────┐                          │
│              │  Master Server │                          │
│              │ 192.168.78.200 │                          │
│              └────────────────┘                          │
└─────────────────────────────────────────────────────────┘
```

---

## Har Gate PC ke Andar

```
┌─────────────────────────────────────────────┐
│              Gate PC                         │
│                                              │
│  ┌─────────────────────────────────────┐    │
│  │         Django Server               │    │
│  │         (Gunicorn)                  │    │
│  │                                     │    │
│  │  ┌────────────┐  ┌───────────────┐  │    │
│  │  │ REST API   │  │  Sync Agent   │  │    │
│  │  │ Entry/Exit │  │  (30s loop)   │  │    │
│  │  └────────────┘  └───────────────┘  │    │
│  │                                     │    │
│  │  ┌─────────────────────────────┐    │    │
│  │  │     ANPR Gate Controller    │    │    │
│  │  │  WebSocket Client           │    │    │
│  │  └─────────────────────────────┘    │    │
│  └─────────────────────────────────────┘    │
│                    │                         │
│  ┌─────────────────────────────────────┐    │
│  │      Local PostgreSQL               │    │
│  │      (localhost)                    │    │
│  │                                     │    │
│  │  toll_trips    accounts             │    │
│  │  transactions  vehicles             │    │
│  │  tags          plazas               │    │
│  │  toll_rates    sync_log             │    │
│  └─────────────────────────────────────┘    │
│                                              │
│  ┌─────────────────────────────────────┐    │
│  │    quick-toll-system (Node.js)      │    │
│  │    LPR Camera → WebSocket :3003     │    │
│  └─────────────────────────────────────┘    │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Camera  │  │ Barrier  │  │ Display  │  │
│  │  (LPR)   │  │ (Serial) │  │ (HTTP)   │  │
│  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────────────────────────┘
```

---

## Vehicle Ka Safar — Entry to Exit

```
ENTRY (Plaza A)
──────────────────────────────────────────────
Camera → plate detect
    ↓
quick-toll-system broadcast (ws://localhost:3003)
    ↓
AnprGateController.on_plate()
    ↓
Plate normalize (KDE-1836 → KDE1836)
    ↓
Vehicle + Tag lookup (local DB)
    ↓
Tag status check (ACTIVE?)
    ↓
EntryService.process_entry()
    ↓
Balance check (≥ Rs.50?)
    ↓
TollTrip CREATE → local DB
    ↓
Barrier OPEN + Display show balance
    ↓
(30s baad) Sync Push → Master DB


EXIT (Plaza B)
──────────────────────────────────────────────
Camera → plate detect
    ↓
AnprGateController.on_plate()
    ↓
ExitService.process_exit()
    ↓
_find_active_trip()
  ├─ Local DB check (trip pulled from master)
  └─ Master fallback (agar sync nahi hua abhi tak)
    ↓
TollRate lookup (A → B ka rate)
    ↓
Balance deduct → local DB
TollTrip UPDATE (status=completed) → local DB
Transaction CREATE → local DB
    ↓
Barrier OPEN + Display show fare
    ↓
(30s baad) Sync Push → Master DB
```

---

## Sync Agent — 30 Second Cycle

```
┌─────────────────────────────────────────────┐
│              Every 30 Seconds                │
│                                              │
│  PULL (Master → Local)                       │
│  ┌──────────────────────────────────────┐   │
│  │ plazas      → full refresh           │   │
│  │ toll_lanes  → full refresh           │   │
│  │ toll_rates  → full refresh           │   │
│  │ tags        → full refresh           │   │
│  │ vehicles    → updated_at filter      │   │
│  │ users       → updated_at filter      │   │
│  │ accounts    → balance_updated_at     │   │
│  │              (timestamp guard)       │   │
│  │ active_trips→ full refresh           │   │
│  │              (cross-plaza exits)     │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  PUSH (Local → Master)                       │
│  ┌──────────────────────────────────────┐   │
│  │ toll_trips  → updated_at filter      │   │
│  │              (entries + exits both)  │   │
│  │ transactions→ processed_at filter    │   │
│  │ accounts    → balance_updated_at     │   │
│  │              (timestamp guard)       │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

---

## Master Server

```
┌─────────────────────────────────────────────┐
│           Master (192.168.78.200)            │
│                                              │
│  ┌─────────────────────────────────────┐    │
│  │      Django Admin Portal            │    │
│  │                                     │    │
│  │  • Vehicles register                │    │
│  │  • Tags issue                       │    │
│  │  • Balance topup                    │    │
│  │  • Reports & stats                  │    │
│  │  • Plaza/Rate management            │    │
│  └─────────────────────────────────────┘    │
│                    │                         │
│  ┌─────────────────────────────────────┐    │
│  │      Master PostgreSQL              │    │
│  │                                     │    │
│  │  Single source of truth             │    │
│  │  All plazas ka data yahan           │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

---

## Offline Scenario (Master Down)

```
Master DOWN
    ↓
Gate PC kaam karta raha hai (local DB)
Entry ✅  Exit ✅  Balance deduct ✅
    ↓
Master BACK UP
    ↓
Next sync cycle (max 30s)
Push → sab kuch master pe
Pull → master se updates local pe
    ↓
Sab PCs sync ✅
```

---

## Cross-Plaza Exit — Timing

```
0s  — Vehicle enters Plaza A  (local A pe save)
30s — Plaza A push → master
60s — Plaza B pull → local B mein active trip aa gayi
      Vehicle exits B → success ✅

Malir Expressway min travel time = 6-8 minutes
Max sync delay = 60 seconds
→ Koi issue nahi
```

---

## Conflict Analysis

| Table | Conflict Risk | Reason |
|-------|--------------|--------|
| toll_trips | None | Entry/exit alag events, timestamp guard |
| accounts | None (practically) | 1 vehicle = 1 active trip at a time |
| transactions | None | Immutable, ON CONFLICT DO NOTHING |
| vehicles/tags | None | Sirf master se update hote hain |

---

## Key Numbers

| Cheez | Value |
|-------|-------|
| Primary DB per gate | Local PostgreSQL (localhost) |
| Sync interval | 30 seconds |
| Cross-plaza trip max delay | 60 seconds |
| Master down tolerance | Unlimited |
| Minimum balance for entry | Rs.50 |
| Plate cooldown (same plate) | 5 seconds |
| Barrier open duration | 2 seconds |

---

## Files — Kahan Kya Hai

| File | Kaam |
|------|------|
| `apps/tolls/sync/agent.py` | Sync agent — 30s loop |
| `apps/tolls/sync/pull_service.py` | Master → Local pull |
| `apps/tolls/sync/push_service.py` | Local → Master push |
| `apps/tolls/sync/connections.py` | psycopg2 connection helpers |
| `apps/tolls/services.py` | EntryService, ExitService |
| `apps/tolls/management/commands/run_anpr_gate.py` | ANPR WebSocket controller |
| `apps/tolls/management/commands/run_gate.py` | RFID gate controller |
| `apps/tolls/apps.py` | Django startup — sync + ANPR auto-start |
| `config/settings/lan.py` | Production settings (LAN, no SSL) |
| `gunicorn.conf.py` | Gunicorn config (1 worker, 4 threads) |
| `mtag.service` | systemd service file |
| `anpr_config.ini` | Gate PC config (plaza, mode, IPs) |

---

## Environment — .env

```ini
DB_HOST=localhost              # Gate PC ka local PostgreSQL
DB_FALLBACK_HOST=              # No fallback needed
master_pg → 192.168.78.200    # Sync agent explicitly connects here
```

---

## Production Start Command

```bash
# Development
python manage.py runserver

# Production
DJANGO_SETTINGS_MODULE=config.settings.lan \
  gunicorn -c gunicorn.conf.py config.wsgi:application

# systemd (auto-start on boot)
sudo systemctl start mtag
sudo systemctl enable mtag
```
