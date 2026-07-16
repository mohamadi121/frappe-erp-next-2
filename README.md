# ASOUD ERP Frappe App

افزونه اختصاصی ASOUD برای حسابداری ایرانی روی ERPNext/Frappe.

## قابلیت‌های نسخه 0.3.1

- تنظیمات تعهدی ASOUD
- گروه تفصیلی
- تفصیلی شناور
- نگاشت حساب به گروه تفصیلی
- تولید خودکار کد تفصیلی
- تولید خودکار کد گروه، کل و معین بر اساس الگوی قابل تنظیم
- API نسخه ۱ برای Flutter
- قرارداد پاسخ یکسان برای تمام APIهای اختصاصی
- CI برای بررسی قالب کد، کامپایل پایتون و تست قرارداد API

## نصب

```bash
bench get-app /path/to/asoud-backend
bench --site your-site.local install-app asoud_erp
bench --site your-site.local migrate
```

## بررسی توسعه

```bash
python -m compileall -q asoud_erp
ruff check .
pytest -q
```

CI سبک مخزن، ساختار مستقل افزونه را بررسی می‌کند. تست یکپارچه کامل باید پس از نصب
روی یک سایت واقعی Frappe/ERPNext اجرا شود.
