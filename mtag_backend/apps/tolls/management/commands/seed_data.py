from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Seed database with Malir Expressway data'

    def handle(self, *args, **kwargs):
        from apps.users.models import User
        from apps.vehicles.models import Vehicle, Tag
        from apps.accounts.models import Account
        from apps.tolls.models import Plaza, TollLane, TollRate

        self.stdout.write('Seeding data...')

        # ── Users ─────────────────────────────────────────────────────────────
        if not User.objects.filter(phone='03001234567').exists():
            User.objects.create_superuser(
                phone='03001234567', password='Admin@1234', full_name='System Admin'
            )
            self.stdout.write(self.style.SUCCESS('Admin created: 03001234567 / Admin@1234'))

        operator, created = User.objects.get_or_create(
            phone='03009999999',
            defaults={'full_name': 'Plaza Operator', 'user_role': 'operator'}
        )
        if created:
            operator.set_password('Operator@1234')
            operator.save()
            self.stdout.write(self.style.SUCCESS('Operator created: 03009999999 / Operator@1234'))

        user, created = User.objects.get_or_create(
            phone='03111111111',
            defaults={'full_name': 'Test User', 'cnic': '3520112345671'}
        )
        if created:
            user.set_password('Test@1234')
            user.save()

        # ── Remove old plazas ─────────────────────────────────────────────────
        Plaza.objects.filter(code__in=['LHR-01', 'ISB-01']).delete()

        # ── Malir Expressway plazas (in route order) ───────────────────────────
        plaza_defs = [
            ('KPT',  'Qayyumabad (KPT Interchange)',  '24.9120', '67.1030'),
            ('EBM',  'EBM Causeway',                  '24.9050', '67.1250'),
            ('SHF',  'Shah Faisal Interchange',       '24.8900', '67.1550'),
            ('QBD',  'Quaidabad (N-5 Interchange)',   '24.8700', '67.1900'),
            ('MEG',  'Memon Goth',                    '24.8450', '67.2400'),
            ('M9M',  'M-9 Motorway',                  '24.8100', '67.3200'),
        ]

        plazas = {}
        for code, name, lat, lng in plaza_defs:
            p, _ = Plaza.objects.get_or_create(code=code, defaults={
                'name': name, 'latitude': lat, 'longitude': lng,
            })
            plazas[code] = p
            for lane_no in [1, 2, 3]:
                TollLane.objects.get_or_create(plaza=p, lane_number=lane_no)

        self.stdout.write(self.style.SUCCESS(f'Plazas ready: {", ".join(plazas.keys())}'))

        # ── Toll rate matrix ───────────────────────────────────────────────────
        # Fare rule:
        #   Journeys within the Qayyumabad–Quaidabad segment → Rs. 100 (car)
        #   Journeys that cross Quaidabad toward Memon Goth / M-9 → Rs. 200 (car)
        #   QBD→M9M (long post-Quaidabad leg) → Rs. 200 (car)
        #   Heavy vehicles: 2× car rate (bus Rs. 200/400, truck Rs. 200/500)
        #
        # (entry, exit, car, bus, truck)
        rate_pairs = [
            # ── Short / within-segment (car Rs. 100) ──────────────────────────
            ('KPT', 'EBM',  100, 200, 200),
            ('KPT', 'SHF',  100, 200, 200),
            ('KPT', 'QBD',  100, 200, 200),
            ('EBM', 'SHF',  100, 200, 200),
            ('EBM', 'QBD',  100, 200, 200),
            ('SHF', 'QBD',  100, 200, 200),
            ('QBD', 'MEG',  100, 200, 200),
            ('MEG', 'M9M',  100, 200, 200),
            # ── Long / crossing Quaidabad (car Rs. 200) ───────────────────────
            ('KPT', 'MEG',  200, 400, 500),
            ('KPT', 'M9M',  200, 400, 500),
            ('EBM', 'MEG',  200, 400, 500),
            ('EBM', 'M9M',  200, 400, 500),
            ('SHF', 'MEG',  200, 400, 500),
            ('SHF', 'M9M',  200, 400, 500),
            ('QBD', 'M9M',  200, 400, 500),
        ]

        rate_count = 0
        for entry_code, exit_code, car, bus, truck in rate_pairs:
            entry = plazas[entry_code]
            exit_ = plazas[exit_code]
            for vtype, amount in [('car', car), ('bus', bus), ('truck', truck)]:
                # both directions, same rate
                for ep, xp in [(entry, exit_), (exit_, entry)]:
                    TollRate.objects.get_or_create(
                        entry_plaza=ep, exit_plaza=xp,
                        vehicle_type=vtype,
                        effective_from='2025-01-01',
                        defaults={'rate': str(amount)},
                    )
                    rate_count += 1

        self.stdout.write(self.style.SUCCESS(f'{rate_count} toll rates configured'))

        # ── Test vehicles ──────────────────────────────────────────────────────
        from datetime import date
        for plate, serial in [('KHI-1001', 'MTAG000001'), ('KHI-1002', 'MTAG000002')]:
            v, created = Vehicle.objects.get_or_create(
                plate_number=plate,
                defaults={'vehicle_type': 'car', 'owner': user}
            )
            if created:
                Tag.objects.create(vehicle=v, tag_serial=serial, expiry_date=date(2099, 12, 31))
                Account.objects.create(vehicle=v, user=user, balance='5000.00')

        self.stdout.write(self.style.SUCCESS('Seed complete!'))
        self.stdout.write('')
        self.stdout.write('── Malir Expressway Plazas ──────────────────────')
        self.stdout.write('  KPT  Qayyumabad (KPT Interchange)   0 km')
        self.stdout.write('  EBM  EBM Causeway                   ~4 km')
        self.stdout.write('  SHF  Shah Faisal Interchange        9 km')
        self.stdout.write('  QBD  Quaidabad (N-5 Interchange)    15 km')
        self.stdout.write('  MEG  Memon Goth                     ~22 km')
        self.stdout.write('  M9M  M-9 Motorway                   39 km')
        self.stdout.write('')
        self.stdout.write('── Rates ────────────────────────────────────────')
        self.stdout.write('  Car:   Rs. 100 (short) / Rs. 200 (long/M-9)')
        self.stdout.write('  Bus:   Rs. 200 (short) / Rs. 400 (long/M-9)')
        self.stdout.write('  Truck: Rs. 200 (short) / Rs. 500 (long/M-9)')
        self.stdout.write('  Note: Motorcycles not permitted on expressway')
        self.stdout.write('')
        self.stdout.write('── Credentials ──────────────────────────────────')
        self.stdout.write('  Admin:    03001234567 / Admin@1234')
        self.stdout.write('  Operator: 03009999999 / Operator@1234')
        self.stdout.write('  Test:     03111111111 / Test@1234')
        self.stdout.write('  Tags:     MTAG000001 (KHI-1001), MTAG000002 (KHI-1002)')
