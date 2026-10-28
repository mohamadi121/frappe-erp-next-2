# معرفی‌نامه پرسنل به بانک‌ها و سازمان‌ها

ماژول صدور و مدیریت معرفی‌نامه‌های پرسنلی به مراجع، بانک‌ها و سازمان‌ها. این ماژول دارای دو بخش اصلی است: طراحی و مدیریت قالب‌های نسخه‌دار (توسط طراحان قالب با دسترسی مدیریت) و صدور عملیاتی معرفی‌نامه برای پرسنل (توسط کارشناسان و مدیران منابع انسانی).

دسترسی‌ها برای هر فراخوان و در سطح شرکت و دامنهٔ سند کنترل می‌شوند.

`get_template` همچنین `can_manage_template` (بولی) را از دسترسی واقعی کاربر برمی‌گرداند؛ فقط مدیر سیستم یا مدیر منابع انسانی می‌تواند قالب را ذخیره یا منتشر کند. نبود این کلید در سرور قدیمی به معنی نداشتن دسترسی مدیریت در برنامه است.

### گردش کار صدور

- کلید اختیاری `workflow` در `save_template_draft` شناسهٔ یک گردش کار آمادهٔ همین شرکت در ماژول موجود است؛ هدف آن باید `ASOUD Workflow Request` باشد و نباید از نوع قالب سیستمی دیگری باشد. مقدار خالی یعنی سیاست فعلی صدور مستقیم اسناد منابع انسانی. این کلید در نسخهٔ منتشرشده و snapshot سند ثابت می‌ماند.
- پاسخ قالب شامل `workflow` و، فقط برای طراح مجاز، `workflow_options: [{name, title}]` است. گزینه‌ها گردش‌های آمادهٔ قابل ارسال شرکت هستند. برنامه فقط عنوان فارسی را نمایش می‌دهد.
- `finalize_letter` با گردش تنظیم‌شده، از `workflow_request.create_request` استفاده می‌کند؛ پاسخ `Pending` است و شمارهٔ رسمی ندارد. فقط رویداد `Completed` از گردش واقعی سند را `Final` می‌کند. رویدادهای رد، لغو و شکست به ترتیب `Rejected`، `Cancelled` و `Failed` می‌شوند. تلاش مجدد همان سند و همان گردش را برمی‌گرداند.
- گردش تنظیم‌شدهٔ غیرفعال، حذف‌شده یا متعلق به شرکت دیگر هرگز به صدور مستقیم منجر نمی‌شود. نبود گردش تنظیم‌شده همان سیاست فعلی منابع انسانی را اجرا می‌کند: صدور مستقیم و یک‌باره.
- شمارهٔ رسمی از الگوی مشترک `request_templates.base.number_pattern('INTRO', date)` و شمارندهٔ استاندارد Frappe گرفته می‌شود: `INTRO-<سال جلالی>-<چهار رقم>`. سری خصوصی سال میلادی حذف می‌شود. شماره‌های قبلی حفظ می‌شوند.
- پس از ارسال، ذخیرهٔ مجدد پیش‌نویس مجاز نیست. چاپ نهایی ذخیره‌شده ثابت می‌ماند و دوباره از اطلاعات کارمند، قالب یا سربرگ جاری ساخته نمی‌شود.
- استقرار: بارگذاری hook جدید رویداد گردش و راه‌اندازی مجدد پردازش‌های سرور؛ تغییر DocType یا مهاجرت داده لازم نیست.

## قالب معرفی‌نامه

| متد | نوع | پارامترها | خروجی |
| --- | --- | --- | --- |
| `personnel_introduction_letters.get_template` | GET | `company` | اطلاعات قالب فعال یا پیش‌نویس قابل ویرایش: `{name, revision, status, clauses, required_recipient, required_purpose, has_expiry}` |
| `personnel_introduction_letters.save_template_draft` | POST | `company`, `revision`, `clauses`, `required_recipient?`, `required_purpose?`, `has_expiry?` | ذخیره پیش‌نویس جدید قالب با نسخهٔ افزایشی |
| `personnel_introduction_letters.publish_template` | POST | `company`, `revision` | انتشار نسخهٔ غیرقابل‌تغییر (Immutable) |

هر بند دارای `{id, title, body, enabled}` است و از شناسه‌های پایدار متغیرها با ساختار `{{group.field}}` یا براکت‌های استاندارد فارسی استفاده می‌کند. مقادیر پیش‌فرض عبارتند از:
- `{{employee.employee_name}}`: نام و نام خانوادگی
- `{{employee.national_id}}`: کد ملی
- `{{employee.employee_number}}`: کد پرسنلی
- `{{employee.designation}}`: عنوان شغلی
- `{{employee.department}}`: واحد سازمانی
- `{{company.company_name}}`: نام قانونی شرکت
- `{{company.representative}}`: نماینده قانونی / مدیرعامل
- `{{company.representative_position}}`: سمت نماینده قانونی
- `{{letter.recipient}}`: نام مرجع / بانک و شعبه
- `{{letter.purpose}}`: هدف معرفی‌نامه
- `{{letter.notes}}`: توضیحات اختصاصی
- `{{letter.number}}`: شماره معرفی‌نامه
- `{{letter.issue_date}}`: تاریخ صدور
- `{{letter.validity_date}}`: تاریخ اعتبار معرفی‌نامه

قالب منتشرشده غیرقابل‌تغییر است و تغییرات بعدی قالب روی اسناد صادرشده قبلی اثری ندارد. معرفی‌نامه طبق موکاپ و ضوابط حریم خصوصی فاقد هرگونه تعهد مالی خودکار یا افشای حقوق پرسنل است.

## صدور، فهرست و چاپ

| متد | نوع | پارامترها | خروجی |
| --- | --- | --- | --- |
| `personnel_introduction_letters.get_employee_options` | GET | `company` | فهرست پرسنل فعال شرکت: `[{employee, employee_name, employee_number, national_id, designation, department, work_location, date_of_joining}]` |
| `personnel_introduction_letters.list_letters` | GET | `company`, `query?`, `status?`, `start?`, `page_length?` | `{items, total}` همراه با جست‌وجوی سرور روی نام، کد پرسنلی، شماره سند و مخاطب پس از همسان‌سازی حروف و ارقام فارسی/انگلیسی |
| `personnel_introduction_letters.get_letter` | GET | `name` | جزئیات سند، نسخهٔ قالب، snapshot داده‌ها و خروجی چاپی `print_html` |
| `personnel_introduction_letters.save_draft` | POST | `company`, `employee`, `recipient_type?`, `recipient_name?`, `bank_name?`, `branch_name?`, `purpose?`, `validity_date?`, `notes?`, `request_key`, `revision?`, `name?` | ایجاد یا به‌روزرسانی پیش‌نویس معرفی‌نامه به صورت idempotent |
| `personnel_introduction_letters.finalize_letter` | POST | `name`, `revision`, `request_key` | ارسال به گردش تنظیم‌شده یا صدور مستقیم طبق سیاست منابع انسانی؛ شماره از سرویس مشترک پس از تأیید نهایی تخصیص می‌یابد |

### جزئیات اعتبارسنجی و قوانین کاری
- پارامتر `request_key` برای عملیات `save_draft` و `finalize_letter` جهت تضمین خاصیت Idempotency اجباری است.
- پارامتر `revision` برای کنترل همروندی خوش‌بینانه (Optimistic Concurrency) استفاده می‌شود.
- وضعیت‌ها شامل `Draft` (پیش‌نویس)، `Pending` / `In Progress` (در جریان) و `Final` (نهایی) هستند.
- در پیش‌نویس، خروجی چاپ دارای عبارت مشخص «پیش‌نویس ـ فاقد اعتبار نهایی» بوده و فاقد امضا یا شماره رسمی است.
- پس از صدور نهایی، سند در وضعیت `Final` قفل شده و snapshot متن و فیلدها ثابت می‌ماند.
- فرمت تاریخ‌های نمایشی شمسی (جلالی) و ارقام با فونت و ارقام استاندارد فارسی است.
