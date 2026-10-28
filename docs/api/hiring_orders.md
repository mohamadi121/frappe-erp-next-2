# احکام استخدام — `asoud_erp.api.v1.hiring_orders`

این ماژول حکم استخدام را از Employee، Department، Salary Structure Assignment و قالب منتشرشدهٔ فرم‌ساز می‌سازد؛ جایگزین رکوردهای اصلی نیست.

همهٔ پاسخ‌ها envelope استاندارد `success(data, meta)` هستند. خواندن و نوشتن برای `HR Manager` و `System Manager` است و شرکت در همهٔ مسیرها کنترل می‌شود. اطلاعات حقوق فقط برای `Payroll Manager` یا `Accounts Manager` داده می‌شود؛ در غیر این صورت 403 با پیام فارسی است.

## قالب

| روش | نوع | ورودی | خروجی |
| --- | --- | --- | --- |
| `get_hiring_order_template` | GET | `company` | نسخهٔ منتشرشدهٔ یگانه، یا `template: null` |
| `save_hiring_order_template` | POST | `company`, `revision`, `template` | پیش‌نویس با revision تازه |
| `publish_hiring_order_template` | POST | `company`, `revision` | نسخهٔ منتشرشدهٔ تغییرناپذیر |

`template` شامل `articles` و `payroll_rows` است. هر article دارای `id` پایدار، `title` و `body` است. هر payroll row دارای `id` پایدار، `title`، `period` (`monthly`، `yearly` یا `one_off`) و `field_ref` است. نگاشت با id و `field_ref` است نه برچسب. قالب پیش‌فرض شش ماده دارد. تغییر نسخهٔ منتشرشده یک پیش‌نویس تازه می‌سازد؛ نسخه‌ها و حکم‌های قبلی بازنویسی نمی‌شوند.

## دادهٔ فرم صدور

| روش | نوع | ورودی | خروجی |
| --- | --- | --- | --- |
| `list_hiring_order_people` | GET | `company`, `search?`, `limit_start?`, `limit_page_length?` | `[{name, display_name, employee_number, department, designation}]` با صفحه‌بندی |
| `get_hiring_order_payroll_catalog` | GET | `company` | `{items: [{field_id, label, type, group}]}` کاتالوگ اقلام حقوق و دستمزد |
| `get_hiring_order_payroll` | GET | `company`, `employee`, `effective_date` | `{currency, rows}`؛ مقدار ناموجود `amount: null, state: "missing", message: "اطلاعات موجود نیست"` |

`effective_date` از `issue_date` و `drafted_on` مستقل است. مبالغ در زمان ذخیره snapshot می‌شوند؛ صفر جانشین مقدار ناموجود نیست.

کاتالوگ فقط برای نقش‌های حقوق قابل دریافت است. `field_id` منبع یکی از `base`، `variable` یا `component.<Salary Component.name>` فعال است؛ ذخیرهٔ قالب منبع ناشناخته را رد می‌کند. شناسهٔ `id` ردیف قالب مستقل از منبع و عنوان می‌ماند. صدور فقط ردیف‌های نسخهٔ منتشرشده را از آخرین قرارداد تأییدشده با `from_date <= effective_date` حل می‌کند؛ `payroll_rows` ارسالی مشتری مبنای مبلغ نیست. اقلام فرمولی که مقدار محاسبه‌شده ندارند ناموجود می‌مانند. تاریخ‌های میلادی ISO در چاپ با تبدیل واقعی شمسی نمایش داده می‌شوند؛ تاریخ شمسی قبلی حفظ می‌شود.

## احکام

| روش | نوع | ورودی | خروجی |
| --- | --- | --- | --- |
| `list_hiring_orders` | GET | `company`, `search?`, `status?`, `limit_start?`, `limit_page_length?` | `{items: [summary]}` و meta صفحه‌بندی |
| `get_hiring_order` | GET | `name` | حکم کامل شامل `template_snapshot`, `values_snapshot`, `payroll_snapshot`, `revision` |
| `save_hiring_order` | POST | `company`, `request_id`, `revision?`, `order?`, `employee`, `effective_date`, `issue_date?`, `drafted_on?`, `values`, `payroll_rows` | پیش‌نویس idempotent |
| `send_hiring_order_for_review` | POST | `name`, `revision`, `request_id` | وضعیت workflow یا سیاست جاری، بدون شمارهٔ رسمی پیش از نهایی‌شدن |
| `print_hiring_order` | GET | `name` | `{html, status, number, draft_banner}` |

`summary` شامل `name`, `number`, `employee`, `employee_name`, `status`, `status_label`, `effective_date`, `issue_date`, `drafted_on`, `revision` است. جست‌وجو نام، کد پرسنلی و شماره را با نرمال‌سازی ی/ي، ک/ك و ارقام فارسی/عربی/لاتین انجام می‌دهد.

فقط فیلدهای قابل‌پرکردن قالب پذیرفته می‌شوند؛ مقدارهای پرسنل، شرکت و حقوق سروری‌اند. revision ناهماهنگ با پیام فارسی رد می‌شود. جمع ماهانه فقط اقلام ماهانه را جمع می‌کند. چاپ پیش‌نویس/درجریان دارای «پیش‌نویس ـ فاقد اعتبار نهایی» است. شمارهٔ رسمی فقط در نهایی‌سازی سرویس موجود صادر می‌شود؛ امضا یا مهر ساختگی نداریم. لغو، اصلاح و صدور مجدد فقط از امکانات موجود سند/گردش‌کار استفاده می‌کند.

## خطاها

ارسال حکم با `request_id` هشت تا صد نویسه‌ای، روی ردیف حکم قفل و تکرارپذیر است. کلید اختیاری `workflow` در نسخهٔ منتشرشدهٔ قالب، همان گردش‌کار آمادهٔ شرکت در ماژول موجود است؛ ارسال از `workflow_request.create_request` استفاده می‌کند و حکم فقط پس از رویداد واقعی `Completed` نهایی می‌شود. رویدادهای رد، لغو و شکست هرگز حکم نهایی نمی‌سازند. اگر قالب گردش‌کار ندارد، مطابق سیاست صدور مستقیم اسناد منابع انسانی موجود، کاربر مجاز صدور می‌تواند حکم را نهایی کند. شمارهٔ رسمی از سرویس نام‌گذاری Frappe در نهایی‌سازی گرفته می‌شود؛ نسخهٔ قالب و snapshot حقوق حفظ می‌شوند. تکرار همان شناسه نتیجهٔ قبلی را برمی‌گرداند؛ شناسهٔ متفاوت روی حکم ارسال‌شده یا revision ناهماهنگ رد می‌شود.

- «قالب منتشرشدهٔ حکم استخدام برای این شرکت وجود ندارد.»
- «اطلاعات موجود نیست» برای قلم حقوق فاقد منبع؛ هرگز صفر نیست.
- «شما اجازهٔ مشاهدهٔ اطلاعات حقوق را ندارید.»
- «پرسنل انتخاب‌شده در این شرکت یافت نشد.»
- «وضعیت یا نسخهٔ حکم برای این اقدام معتبر نیست.»
- «این حکم توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید.»
