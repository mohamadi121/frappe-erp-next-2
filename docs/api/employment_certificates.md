# گواهی‌های اشتغال به کار

این ماژول مستقل از «درخواست گواهی اشتغال» و `certificate_issue` است. تنها مدیر منابع انسانی یا مدیر کلِ دارای دسترسی شرکت می‌تواند قالب و گواهی را ببیند یا تغییر دهد؛ مجوزها در هر فراخوان و برای هر سند کنترل می‌شوند.

## قالب

| method | verb | arguments | result |
| --- | --- | --- | --- |
| `employment_certificates.get_template` | GET | `company` | آخرین نسخهٔ منتشرشده یا پیش‌نویس قابل ویرایش: `{name, revision, status, clauses, salary_enabled, salary_rows}` |
| `employment_certificates.save_template_draft` | POST | `company`, `revision`, `clauses`, `salary_enabled`, `salary_rows` | پیش‌نویس نسخهٔ بعدی با `revision` تازه |
| `employment_certificates.publish_template` | POST | `company`, `revision` | نسخهٔ منتشرشدهٔ immutable |

هر بند `{id, title, body, enabled}` است و جای‌نگهدارها با شناسهٔ پایدار منبع (`{{employee.employee_name}}`، نه برچسب فارسی) ذخیره می‌شوند. `salary_rows` فقط شناسهٔ عددی مجاز حقوق و دورهٔ آن را ذخیره می‌کند. حذف یا غیرفعال‌شدن منبع، انتشار را با پیام فارسی متوقف می‌کند. قالب منتشرشده هرگز overwrite نمی‌شود.

## صدور و فهرست

| method | verb | arguments | result |
| --- | --- | --- | --- |
| `employment_certificates.list_certificates` | GET | `company`, `query?`, `status?`, `start?`, `page_length?` | `{items, total}`؛ جست‌وجوی سرور نام، کد پرسنلی، شماره و مخاطب را پس از همسان‌سازی ی/ي، ک/ك و رقم‌ها انجام می‌دهد. |
| `employment_certificates.get_certificate` | GET | `name` | سند، نسخهٔ قالب، snapshot، و HTML چاپی؛ دادهٔ حقوق فقط هنگام مجازبودن برمی‌گردد. |
| `employment_certificates.save_draft` | POST | `company`, `employee`, `addressee_type?`, `addressee_name`, `addressee_title?`, `purpose?`, `request_key`, `revision?` | پیش‌نویس یا نتیجهٔ همان `request_key`؛ چند گواهی معتبر برای یک شخص/مخاطب ممکن است. |
| `employment_certificates.finalize_certificate` | POST | `name`, `revision`, `request_key` | سند نهایی با شمارهٔ خدمت شماره‌گذاری، نسخهٔ قالب و snapshot غیرقابل‌تغییر. |

`save_draft` و `finalize_certificate` با `request_key` اجباری idempotent هستند؛ تطابق‌نداشتن payload همان کلید خطای فارسی دارد. `revision` برای optimistic concurrency اجباری است مگر ایجاد تازه. وضعیت‌ها `Draft`، وضعیت واقعی گردش‌کار (در صورت وجود) و `Final` هستند. اگر گردش‌کار تطبیق‌داده‌شده وجود داشته باشد، نهایی‌سازی آن را اجرا می‌کند؛ در غیر این صورت سیاست جاری سامانه اعمال می‌شود.

کارمند باید Active باشد مگر سیاست سامانه خلافش را تعیین کرده باشد؛ تاریخ شروع فقط از Employee خوانده می‌شود. بخش حقوق فقط زمانی resolve و snapshot می‌شود که قالب آن را فعال کرده باشد، کاربر مجوز حقوق داشته باشد و سیاست حریم شرکت اجازه دهد. مقدار گم‌شده «اطلاعات موجود نیست» است، نه صفر. در غیر این صورت، API، HTML و چاپ هیچ دادهٔ حقوقی ندارند.

چاپ `print_html`، A4 راست‌به‌چپ با Letter Head/Footer مشترک و شماره صفحه است. چاپ پیش‌نویس عبارت «پیش‌نویس ـ فاقد اعتبار نهایی» دارد؛ امضا یا مهر ساختگی ندارد.

خطاهای اعتبارسنجی 417 و خطاهای مجوز/دامنهٔ شرکت 403 هستند و همگی پیام فارسی دارند. استقرار اولیه نیازمند migration برای DocType `ASOUD Employment Certificate` و restart است.

متن بند و مقادیر جای‌نگهدار در چاپ به‌صورت متن امن escape می‌شوند؛ HTML ورودی اجرا نمی‌شود.
