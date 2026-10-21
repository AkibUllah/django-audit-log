"""Create demo data and a few audited changes so the admin has something to show."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from audit_log import audit_context, disable_auditing
from audit_log.bulk import bulk_update_audited
from audit_log.models import AuditEntry
from shop.models import Customer, Order, Product, Tag


class Command(BaseCommand):
    help = "Seed the example shop with products, a customer, an order and audited edits."

    def handle(self, *args, **options):
        User = get_user_model()
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={"is_staff": True, "is_superuser": True, "email": "admin@example.com"},
        )
        # A freshly created user has an empty password string, which Django 4.2 still reports
        # as "usable", so check for that explicitly; an existing real password is left alone.
        if created or not admin.password or not admin.has_usable_password():
            admin.set_password("admin12345")
            admin.save()

        with disable_auditing():  # reference data: not interesting in the trail
            tags = {
                n: Tag.objects.get_or_create(name=n)[0] for n in ("grocery", "fashion", "eid-offer")
            }

        with audit_context(actor=admin, request_id="seed-shop"):
            rice, _ = Product.objects.get_or_create(
                sku="RICE-MINI-5",
                defaults={"name": "Miniket Rice 5 kg", "price_bdt": Decimal("395.00")},
            )
            panjabi, _ = Product.objects.get_or_create(
                sku="PANJ-WHT-L",
                defaults={"name": "Cotton Panjabi (L)", "price_bdt": Decimal("1450.00")},
            )
            rice.tags.add(tags["grocery"])
            panjabi.tags.add(tags["fashion"], tags["eid-offer"])

            customer, _ = Customer.objects.get_or_create(
                nid_number="1990123456789",
                defaults={
                    "name": "Rahim Uddin",
                    "phone": "01711223344",
                    "address": "House 12, Road 5, Dhanmondi, Dhaka",
                },
            )
            customer.phone = "01999887766"  # masked in the trail
            customer.save()

            order, created = Order.objects.get_or_create(
                customer=customer,
                product=panjabi,
                defaults={"quantity": 2, "total_bdt": Decimal("2900.00")},
            )
            if created:
                order.status = Order.Status.PAID
                order.save()

            bulk_update_audited(
                Product.objects.filter(sku__startswith="RICE"), price_bdt=Decimal("410.00")
            )

        total = AuditEntry.objects.count()
        self.stdout.write(
            self.style.SUCCESS(f"Seeded. Audit entries: {total}. Admin login: admin / admin12345")
        )
