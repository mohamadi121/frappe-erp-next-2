# ۴۱ — اتصال فرم‌ساز، موجودیت‌ها و منابع داده

تاریخ: ۱۴۰۵/۰۸/۲۳ = 2026-11-14؛ مبنای ممیزی: اپ `c324e9e`، بک‌اند `448855f`. این سند تلفیق شواهد پذیرفته‌شدهٔ A1 تا A6 با تقدم REVIEW-NOTES.md است. بررسی کد یا اجرای مجدد تست در A7 انجام نشده است. ارجاع فایل و خط، مربوط به مبنای ممیزی است.

## دامنهٔ اثبات اتصال

وجود preset و سرویس ensure_builtin مدرک وجود کد و قابلیت انتشار است؛ موجودی رکوردهای منتشرشدهٔ دیتابیس هیچ‌یک از ده درخواست و شش سند را ثابت نمی‌کند. علامت‌های ✔ در ماتریس A5 به معنی مسیر پیاده‌سازی هستند و اجرای موفق زندهٔ همهٔ ترکیب‌ها نیستند. نقص tuple، request_key، Available، نگاشت پیوست و Update Fields روی Form Entry استثناهای این مسیرها هستند.

فهرست قراردادها گزارش است؛ فرم تراکنشی مستقل محسوب نمی‌شود. تمدید/الحاقیه عملیات قرارداد است و قالب فرم مستقل در ورودی‌ها اثبات نشده است. کاتالوگ تمام موجودیت‌های واقعاً منتشرشدهٔ سایر ماژول‌ها بدون دسترسی دیتابیس بررسی‌نشده باقی می‌ماند.


<!-- شواهد منقول از A5.md، خطوط 29 تا 179 -->
### ۲۰. اتصال به فرم‌ساز (Form Builder Integration)

در این بخش ۹ سوال کلیدی مطرح در بند ۲۰ پلان ممیزی با تکیه بر کدهای واقعی سیستم بررسی و ردگیری شده است:

#### ۱. فیلدهای فرم چگونه دریافت می‌شوند؟
- **مکانیسم فنی:** فیلدهای فرم از طریق تابع `catalog` در فایل `asoud_erp/services/workflow_condition_binding.py:97-150` برای شروط و از طریق `schema_sources` در `asoud_erp/services/automatic_action_metadata.py:85-115` برای اقدامات خودکار دریافت می‌شوند.
- **ردگیری مسیر داده:** گردش‌کار از فیلد `source_revision` خود، سند `ASOUD Form Revision` مربوطه را بارگذاری می‌کند (`workflow_condition_binding.py:107-108`). فیلد متنی `schema_json` پارس شده و فیلدهای طرح‌واره با تابع `fields()` در `asoud_erp/services/form_schema.py:143-148` به صورت مسطح (Flattened) استخراج می‌گردند.
- **تبدیل انواع:** تابع `_fields` در `workflow_condition_binding.py:54-93` فیلدها را بر اساس `TYPE_MAP` (خطوط ۱۱-۲۴) به انواع استاندارد موتور شرط تبدیل کرده و برای استفاده در UI طراح گردش‌کار برمی‌گرداند.

#### ۲. آیا شناسه فیلدها پایدار است؟ (Key vs Label)
- **مکانیسم اعتبارسنجی:** بله، در سطح دیتابیس و اعتبارسنجی طرح‌واره (`asoud_erp/services/form_schema.py:199-204`)، هر فیلد ملزم به داشتن کلید یکتای انگلیسی مطابق الگوی باقاعده `^[a-z][a-z0-9_]{0,59}$` است.
- **اتصال در موتور شرط:** در موتور شروط (`workflow_condition_binding.py:71-77`) فیلدها صرفاً بر اساس شناسه `source_field: key` مقایسه و متصل می‌شوند. فیلد `label` صرفاً برای نمایش در واسط کاربری ذخیره می‌شود. تغییر برچسب (Label) در بازبینی‌های بعدی هیچ اثری بر ارزیابی شروط یا نگاشت‌ها ندارد.

#### ۳. آیا فیلدهای تاریخ و زمان درست شناسایی می‌شوند؟
- **مکانیسم شناسایی:** انواع داده در `asoud_erp/services/form_schema.py:10` شامل `Date`, `Time`, `DateTime` تعریف شده‌اند.
- **نگاشت در موتور شرط:** در `workflow_condition_binding.py:16-24`, نوع `Date` به `Date`، نوع `DateTime`/`Datetime` به `DateTime` و نوع `Time` به `Time` نگاشت می‌شوند.
- **اعتبارسنجی مقادیر:** در زمان ثبت و ارزیابی شروط (`asoud_erp/services/form_schema.py:897-906` و `workflow_condition_binding.py:240-247`)، تبدیل رشته‌های ایزو با کلاس‌های استاندارد `datetime.date.fromisoformat` و `datetime.time.fromisoformat` انجام می‌شود. همچنین فیلدهای کمکی جابه‌جایی به روز بعد (`<key>__next_day`) در `form_schema.py:80-82, 947-954` پشتیبانی می‌شوند تا ساعت‌های شبانه‌روزی بدون حدس تاریخ به درستی مقایسه شوند.

#### ۴. آیا فیلدهای شرط پویا هستند؟
- **مکانیسم:** بله، تابع `catalog` در `workflow_condition_binding.py:97-150` فهرست فیلدها را به صورت کاملاً پویا از سه منبع استخراج می‌کند:
  1. فیلدهای فرم متصل به گردش‌کار (`source_kind: Original`).
  2. فیلدهای مراحل قبلی گردش‌کار بر اساس گراف پیش‌نیاز قطعی (`source_kind: Stage` حاصل از `guaranteed_predecessors`).
  3. فیلدهای سیستمی ثابت شامل `started_by`, `started_on`, `requester_unit` (`source_kind: System`).
- **گزینه‌های فیلدهای انتخابی:** گزینه‌های فیلدهای انتخابی (`Select`, `MultiSelect`) و برچسب‌های گزینه‌ها نیز به شکل پویا از تعریف فیلد در فرم خوانده شده و برای مقایسه در شروط ارسال می‌شوند (`workflow_condition_binding.py:65-72`).

#### ۵. آیا فیلدهای عملیات خودکار معتبر هستند؟
- **مکانیسم اعتبارسنجی:** در `asoud_erp/services/automatic_action_metadata.py:215-235` و `asoud_erp/services/automatic_action_runtime.py:46-56`, منابع مجاز برای فیلدهای عملیات خودکار اعتبارسنجی می‌شوند.
- **محدودیت کشف‌شده:** در کارهای خودکار، اگر گردش‌کار دارای فرم متصل باشد، موجودیت منبع به `ASOUD Form Entry` نگاشت می‌شود (`automatic_action_metadata.py:220`). با این حال، در زمان به‌روزرسانی فیلدها (`Update Fields`) در تابع `_update` در `automatic_action_runtime.py:110-128`, فقط شاخه‌های `ASOUD Workflow Request` و DocTypeهای نیتیو Frappe پشتیبانی شده‌اند؛ در صورتی که رکورد هدف `ASOUD Form Entry` باشد، متد `_update` با فراخوانی `doc.update(values)` و `doc.save()` خطای فیلد ناموجود صادر می‌کند زیرا مقادیر فرم در جدول ذخیره نشده‌اند بلکه به صورت JSON در فیلد `values_json` قرار دارند (به یافته‌های ممیزی مراجعه شود).

#### ۶. تغییر فرم چه اثری بر گردش‌کار متصل دارد؟
- **طراحی نسخه‌محور:** فرم‌ها دارای مفهوم پیش‌نویس (`draft_json` در `ASOUD Form`) و نسخه منتشرشده (`schema_json` در `ASOUD Form Revision`) هستند (`asoud_erp/api/v1/forms.py:87-101, 240-265`).
- **پایداری اجراها:** گردش‌کار مستقیماً به یک شناسه نسخه خاص (`source_revision`) متصل است نه به خود فرم (`asoud_workflow_definition.json:41`). بنابراین، ویرایش فرم در فرم‌ساز و ایجاد نسخه جدید تا زمانی که در تنظیمات مرحله گردش‌کار نسخه به‌روزرسانی نشود، تأثیری بر گردش‌کارهای در حال اجرا یا آماده ندارد.
- **مسیریابی هوشمند و تشخیص کهنگی (Stale):** در زمان ثبت فرم جدید، تابع `route` در `asoud_erp/services/workflow_submission_source.py:158` فلگ `stale: row.source_revision != revision.name` را محاسبه می‌کند. اگر گردش‌کار روی حالت شرطی (`Conditional`) باشد و نسخه تغییر کرده باشد، سیستم از اجرای مسیر با نسخه نامنطبق جلوگیری کرده و خطای صریح «نسخهٔ فرم مسیر مشروط تغییر کرده است؛ اتصال آن را به‌روزرسانی کنید» می‌دهد (`workflow_submission_source.py:160-162`).

#### ۷. حذف فیلد چگونه مدیریت می‌شود؟
- **قفل تغییرات در فرم منتشرشده:** در `asoud_erp/api/v1/forms.py:246-260`, اگر فرم دارای نسخه فعال باشد، تغییر نوع فیلد منتشرشده مسدود شده و پیام «برای تغییر نوع فیلد منتشرشده، فیلد جدید با شناسه جدید ایجاد کنید» برگردانده می‌شود.
- **اعتبارسنجی اتصال در گردش‌کار:** طبق تابع `assert_editable` در `asoud_erp/services/workflow_condition_binding.py:37-46`, اگر گردش‌کاری در وضعیت `Active` باشد یا دارای نمونه اجرای در حال اجرا (`Running`) باشد، تغییر ساختار آن قفل می‌شود.
- **کنترل جامع شروط در صورت حذف فیلد:** تابع `validate_bindings` در `workflow_condition_binding.py:155-165` در زمان ارزیابی گردش‌کار تک‌تک شروط را با فیلدهای موجود تطبیق می‌دهد؛ در صورت حذف فیلد از فرم، خطای صریح `شرط X: منبع یا فیلد حذف شده یا در این مسیر معتبر نیست` صادر می‌گردد. همچنین در `asoud_erp/services/workflow_check.py:133-138`, سلامت فرم‌های متصل با کد `form_missing` بررسی می‌شود.

#### ۸. نسخه فرم چگونه تشخیص داده می‌شود؟
- **فیلد اختصاصی:** در DocType تعریف گردش‌کار (`asoud_erp/asoud_erp/doctype/asoud_workflow_definition/asoud_workflow_definition.json:41`) فیلد `source_revision` از نوع Link به `ASOUD Form Revision` تعریف شده است.
- **اعتبارسنجی در کنترلر داک‌تایپ:** در کنترلر `asoud_workflow_definition.py:11-30`, در صورت تغییر فیلدهای `source_form` یا `source_revision`، مجوز اختصاصی سرویس اتصال (`flags.submission_source_service`) کنترل می‌شود؛ همچنین بررسی می‌شود که فرم فعال بوده و `form.active_revision == self.source_revision` باشد.
- **ثبت در رکوردهای تراکنشی:** هنگام ثبت فرم در `asoud_erp/api/v1/forms.py:703-705`، فیلد `revision` در جدول `ASOUD Form Entry` شناسه قطعی نسخه فرم را ذخیره می‌کند.

#### ۹. دسترسی به فیلدهای محرمانه و حساس چگونه کنترل می‌شود؟
- **تعریف ویژگی Sensitive:** در طرح‌واره فرم‌ساز، پرچم ب boolean با نام `sensitive` برای هر فیلد قابل تنظیم است (`asoud_erp/services/form_schema.py:217`).
- **حذف از کاتالوگ شروط و عملیات خودکار:** در `workflow_condition_binding.py:64`, فیلدهایی که پرچم `sensitive` دارند به طور خودکار از کاتالوگ فیلدهای قابل انتخاب برای شرط حذف می‌شوند (`if field.get('sensitive'): continue`). همچنین در `automatic_action_metadata.py:94, 198` فیلدهای حساس از فیلدهای خروجی کارهای خودکار فیلتر می‌شوند.
- **ماسک‌گذاری در کارتابل و مشاهده:** ماژول `asoud_erp/services/request_serializer.py:14-65` توابع `mask_sensitive_values` و `overlay_sensitive` را پیاده‌سازی کرده است که مقادیر فیلدهای حساس را برای کاربران غیرمجاز ماسک کرده و متن جایگزین قرار می‌دهد. همچنین پیوست‌های حساس در `request_serializer.py:67-75` پاک می‌شوند و در متن جست‌وجو (`search_text`) در `asoud_erp/api/v1/workflow_request.py:250-256` ذخیره نمی‌شوند.

---

### ۲۱. موجودیت‌ها و رکوردهای مرتبط (Entities and Related Records)

نحوه اتصال فرایندساز به ۵ موجودیت کلیدی مطرح در پلان به شرح زیر است:

#### ۱. درخواست (Request)
- **موجودیت و کنترلر:** DocType با نام `ASOUD Workflow Request` (مسیر `asoud_erp/asoud_erp/doctype/asoud_workflow_request/`).
- **مکانیسم اتصال:** از طریق متد `create_request` در `asoud_erp/api/v1/workflow_request.py:578-650` و متد `submit_form` در `asoud_erp/api/v1/forms.py:672-688`. مقادیر فرم از طریق نگاشت `workflow_key` به فیلدهای درخواست منتقل شده و رکورد درخواست با ارتباط مستقیم به نمونه گردش‌کار (`workflow_instance`) ساخته می‌شود.
- **محدودیت:** فیلدهای پیوست و فایل به دلیل تفاوت در مدل پیوست‌های درخواست، طبق `forms.py:680-682` در نگاشت مستقیم مسدود بوده و خطای «پیوست متصل به گردش‌کار باید از مسیر استاندارد پیوست درخواست ثبت شود» صادر می‌کنند.

#### ۲. سند (Document)
- **موجودیت و کنترلر:** ساخت اسناد رسمی از طریق `api/v1/forms.py:690-705` و ماژول `asoud_erp/services/document_templates.py:17-45`.
- **مکانیسم اتصال:** فرم‌های نوع `Document` دارای نگاشت `native_key` هستند که فیلدهای فرم را به فیلدهای اسناد استاندارد ERPNext (همانند `Journal Entry` و `Material Request`) نگاشت می‌کنند (`forms.py:269-308`). در زمان ثبت، سند با متد `frappe.get_doc(payload).insert()` ساخته شده و سپس رکورد `ASOUD Form Entry` با ارجاع `reference_doctype` و `reference_name` ثبت می‌گردد.
- **محدودیت:** فقط DocTypeهایی که در دیکشنری `NATIVE` در `forms.py:32-35` هاردکد شده‌اند مجازند (`Journal Entry` و `Material Request`). سایر DocTypeها رد می‌شوند.

#### ۳. موجودیت فعلی (Current Entity)
- **مکانیسم اتصال:** در ماژول‌های شروط و کارهای خودکار (`asoud_erp/services/automatic_action_runtime.py:58-75` و `workflow_condition_binding.py:220-235`)، موجودیت فعلی از طریق فیلدهای `reference_doctype` و `reference_name` در نمونه اجرای گردش‌کار (`ASOUD Workflow Instance`) شناسایی می‌شود.
- **محدودیت:** اگر موجودیت فعلی `ASOUD Form Entry` باشد، مقادیر آن از طریق تابع `values(entry)` به عنوان داده خواندنی خوانده می‌شوند، اما طبق بررسی انجام‌شده، به‌روزرسانی فیلدهای آن توسط موتور کارهای خودکار پشتیبانی نشده است.

#### ۴. رکورد مرتبط (Related Record)
- **مکانیسم اتصال:** رکوردهای مرتبط در سیستم از طریق دو مکانیسم مدیریت می‌شوند:
  1. پیوند اسناد ایجادشده توسط مراحل کارهای خودکار که در جدول `ASOUD Workflow Activity` یا فیلدهای کمکی ذخیره می‌شوند (`automatic_action_runtime.py:328-330`).
  2. واکشی اطلاعات از طریق فیلدهای Link با قابلیت `fetch_from` در `asoud_erp/services/form_schema.py:848-860` که مقادیر اسناد متصل (مثل کارمند، انبار، مرکز هزینه) را استخراج می‌کند.
- **محدودیت:** اتصال به رکوردهای مرتبط فقط به صورت خواندنی (Read-Only Fetch) مجاز است و امکان اجرای تراکنش یا تغییر وضعیت روی رکوردهای والد/وابسته در موتور فرم‌ساز فعلی وجود ندارد.

#### ۵. اطلاعات خروجی مرحله قبلی (Previous Stage Output)
- **مکانیسم اتصال:** در موتور شروط از طریق تابع `catalog` در `asoud_erp/services/workflow_condition_binding.py:115-130` با فراخوانی `guaranteed_predecessors` در `asoud_erp/services/workflow_condition.py:1-25` استخراج می‌شود. در زمان اجرا، تابع `resolver` در `workflow_condition_binding.py:225-235` با کوئری زدن به آخرین تسک‌های تکمیل‌شده مرحله (`status = 'Completed'`) مقادیر فیلدها را از `response_json` استخراج و در شروط ارزیابی می‌کند. در اکشن‌های خودکار نیز ماژول `asoud_erp/services/form_execution/parameters.py:40-60` مقادیر تسک‌های تکمیل‌شده مراحل قبلی را تجمیع و بازنویسی می‌کند.
- **محدودیت:** فقط مراحلی که در تمام مسیرهای منتهی به مرحله فعلی به صورت قطعی حضور داشته باشند (`guaranteed_predecessors`) در کاتالوگ در دسترس قرار می‌گیرند تا از خطای عدم وجود داده در شاخه‌های شرطی موازی جلوگیری شود.

---

### ۲۲. منابع انسانی: بررسی جامع ۱۰ درخواست و ۶ سند و فرم

در این بخش ابتدا وجود واقعی، وضعیت انتشار و ساختار هر یک از ۱۰ درخواست و ۶ سند بررسی شده و سپس وضعیت پاسخ به ۶ سوال کلیدی مستند شده است.

#### شواهد وجود و کاتالوگ سیستم:
1. **فایل قالب‌های پیش‌فرض:** تمام ۱۰ درخواست در فایل `asoud_erp/services/hr_form_presets.json` تعریف شده‌اند.
2. **سرویس کاتالوگ:** فایل `asoud_erp/services/hr_form_catalog.py:10-45` کاتالوگ را بارگذاری و از طریق `ensure_builtin` در دیتابیس با نسخه منتشرشده (`Published`) ذخیره می‌کند.
3. **تکرار کلیدها در فایل Presets (بررسی تخصصی):** بررسی دقیق نشان داد که کلیدهای `"training"` و `"equipment"` دقیقاً دو بار در فایل `hr_form_presets.json` ظاهر شده‌اند:
   - کلید `"training"`: یک بار در خط ۱۱۵۷ به عنوان کلید تاپ‌لول دیکشنری درخواست (`"training": { ... }`) و یک بار در خط ۱۲۰۱ به عنوان شناسه بخش درون همان فرم (`"id": "training"`).
   - کلید `"equipment"`: یک بار در خط ۱۶۵۰ به عنوان کلید تاپ‌لول دیکشنری درخواست (`"equipment": { ... }`) و یک بار در خط ۱۷۲۷ به عنوان شناسه بخش درون همان فرم (`"id": "equipment"`).
   این هم‌نامی بین کلید اصلی درخواست و شناسه بخش است و هیچ تداخل یا کلید تکراری در ریشه JSON یا در کلیدهای فیلدها (field keys) وجود ندارد.
4. **ماژول‌های اجرای پس از تأیید (Form Execution):** ماژول‌های اجرایی در دایرکتوری `asoud_erp/services/form_execution/` قرار دارند و در `__init__.py:35-45` در دیکشنری `EXECUTORS` ثبت شده‌اند.

#### جدول ماتریس بررسی ۱۰ درخواست و ۶ سند منابع انسانی:

| ردیف | نام موجودیت | نوع | مدرک وجود در کد / کلید Preset | ماژول اجرای خودکار (`form_execution`) | ۱. اتصال گردش‌کار | ۲. دریافت فیلدها | ۳. انتساب سازمانی | ۴. اجرای شرط | ۵. اکشن خودکار | ۶. ثبت نتیجه نهایی |
|---|---|---|---|---|---|---|---|---|---|---|
| ۱ | مرخصی | درخواست | `hr_form_presets.json:2065` (`leave`) | `leave_application.py` | ✔ `workflow_submission_source.py:1-85` | ✔ `form_schema.py:143-148` | ✔ `workflow_runtime.py:135-180` | ✔ `workflow_condition_binding.py:97-150` | ✔ `leave_application.py:55-100` | ✔ `workflow_end.py:10-55` |
| ۲ | مأموریت | درخواست | `hr_form_presets.json:2239` (`mission`) | `mission.py` | ✔ `workflow_submission_source.py:1-85` | ✔ `form_schema.py:143-148` | ✔ `workflow_runtime.py:135-180` | ✔ `workflow_condition_binding.py:97-150` | ✔ `mission.py:50-95` | ✔ `workflow_end.py:10-55` |
| ۳ | اضافه‌کاری | درخواست | `hr_form_presets.json:2428` (`overtime`) | `overtime.py` | ✔ `workflow_submission_source.py:1-85` | ✔ `form_schema.py:143-148` | ✔ `workflow_runtime.py:135-180` | ✔ `workflow_condition_binding.py:97-150` | ✔ `overtime.py:40-85` | ✔ `workflow_end.py:10-55` |
| ۴ | اصلاح تردد | درخواست | `hr_form_presets.json:2` (`traffic_correction`) | `attendance_correction.py` | ✔ `workflow_submission_source.py:1-85` | ✔ `form_schema.py:143-148` | ✔ `workflow_runtime.py:135-180` | ✔ `workflow_condition_binding.py:97-150` | ✔ `attendance_correction.py:45-90` | ✔ `workflow_end.py:10-55` |
| ۵ | مساعده | درخواست | `hr_form_presets.json:2569` (`salary_advance`) | `employee_advance.py` | ✔ `workflow_submission_source.py:1-85` | ✔ `form_schema.py:143-148` | ✔ `workflow_runtime.py:135-180` | ✔ `workflow_condition_binding.py:97-150` | ✔ `employee_advance.py:45-90` | ✔ `workflow_end.py:10-55` |
| ۶ | درخواست گواهی اشتغال | درخواست | `hr_form_presets.json:486` (`employment_certificate`) | `certificate_issue.py` | ✔ `workflow_submission_source.py:1-85` | ✔ `form_schema.py:143-148` | ✔ `workflow_runtime.py:135-180` | ✔ `workflow_condition_binding.py:97-150` | ✔ `certificate_issue.py:40-95` | ✔ `workflow_end.py:10-55` |
| ۷ | تغییر شیفت | درخواست | `hr_form_presets.json:727` (`shift_change`) | `shift_request.py` | ✔ `workflow_submission_source.py:1-85` | ✔ `form_schema.py:143-148` | ✔ `workflow_runtime.py:135-180` | ✔ `workflow_condition_binding.py:97-150` | ✔ `shift_request.py:45-95` | ✔ `workflow_end.py:10-55` |
| ۸ | درخواست تسویه‌حساب | درخواست | `hr_form_presets.json:3070` (`settlement`) | `exit.py` | ✔ `workflow_submission_source.py:1-85` | ✔ `form_schema.py:143-148` | ✔ `workflow_runtime.py:135-180` | ✔ `workflow_condition_binding.py:97-150` | ✔ `exit.py:50-100` | ✔ `workflow_end.py:10-55` |
| ۹ | آموزش | درخواست | `hr_form_presets.json:1157` (`training`) | `training_enrollment.py` | ✔ `workflow_submission_source.py:1-85` | ✔ `form_schema.py:143-148` | ✔ `workflow_runtime.py:135-180` | ✔ `workflow_condition_binding.py:97-150` | ✔ `training_enrollment.py:45-95` | ✔ `workflow_end.py:10-55` |
| ۱۰ | دریافت و عودت تجهیزات | درخواست | `hr_form_presets.json:1650` (`equipment`) | `asset_movement.py` | ✔ `workflow_submission_source.py:1-85` | ✔ `form_schema.py:143-148` | ✔ `workflow_runtime.py:135-180` | ✔ `workflow_condition_binding.py:97-150` | ✔ `asset_movement.py:45-90` | ✔ `workflow_end.py:10-55` |
| ۱۱ | قرارداد کار | سند | `api/v1/employment_contracts.py:102` (DocType: `Contract`) | `employment_contract_workflow.py` | ✔ `employment_contracts.py:701` | ✔ `employment_contracts.py:321` | ✔ `workflow_assignment.py:1-15` | ✔ `workflow_condition_binding.py:97-150` | ✔ `employment_contracts.py:684` | ✔ `workflow_end.py:10-55` |
| ۱۲ | گواهی اشتغال به کار | سند | `api/v1/employment_certificates.py:18` (DocType: `ASOUD Employment Certificate`) | `employment_certificate_workflow.py` | ✔ `employment_certificates.py:50` | ✔ `certificate_access.py:10-35` | ✔ `workflow_assignment.py:1-15` | ✔ `workflow_condition_binding.py:97-150` | ✔ `certificate_issue.py:40-95` | ✔ `workflow_end.py:10-55` |
| ۱۳ | معرفی‌نامه پرسنل | سند | `api/v1/personnel_introduction_letters.py:18` (DocType: `ASOUD Personnel Introduction Letter`) | `personnel_introduction_letter_workflow.py` | ✔ `personnel_introduction_letters.py:50` | ✔ `personnel_introduction_letters.py:45` | ✔ `workflow_assignment.py:1-15` | ✔ `workflow_condition_binding.py:97-150` | ✔ `personnel_introduction_letters.py:120` | ✔ `workflow_end.py:10-55` |
| ۱۴ | درخواست گواهی اشتغال (فرم) | فرم/درخواست | مشترک با ردیف ۶ (`hr_form_presets.json:486`) | `certificate_issue.py` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| ۱۵ | فهرست قراردادها | گزارش/فهرست | `flutter-asoud-erp/.../hr_contracts_page.dart:339` و `employment_contracts.py:417` | *فاقد ماژول اجرایی* (فهرست داده است) | ✘ (گزارش است، موجودیت تراکنشی نیست) | - | - | - | - | - |
| ۱۶ | تمدید قرارداد و الحاقیه | عملیات سند | فاقد قالب فرم مستقل؛ عملیات درون `employment_contracts.py:516-560` | پیاده‌سازی شده با ایجاد پیش‌نویس قرارداد جدید (`Contract Draft`) | ✔ (از طریق گردش‌کار قرارداد کار) | ✔ | ✔ | ✔ | ✔ | ✔ |

#### بررسی تحلیلی شش سوال برای درخواست‌ها و اسناد:
1. **آیا گردش‌کار قابل اتصال است؟** بله، از طریق سازوکار `submission_source` در مرحله شروع (`asoud_erp/services/workflow_submission_source.py:15-85`)، تمام فرم‌های منتشرشده نوع `Request` و `Document` قابلیت اتصال مستقیم دارند. اسناد اختصاصی قرارداد و معرفی‌نامه نیز دارای سرویس‌های اختصاصی اتصال گردش‌کار (`employment_contract_workflow.py` و `personnel_introduction_letter_workflow.py`) هستند.
2. **آیا فیلدهای فرم قابل دریافت هستند؟** بله، تابع `catalog` در `asoud_erp/services/workflow_condition_binding.py:97-150` تمام فیلدهای فرم را با انواع داده‌ای پایدار استخراج می‌کند.
3. **آیا مسئولان از ساختار سازمانی قابل شناسایی‌اند؟** بله، تابع `_users_for_stage` در `asoud_erp/api/v1/workflow_runtime.py:135-180` انواع انتساب شامل `Direct Manager` (گزارش به مدیر مستقیم از طریق فیلد `reports_to` در کارمند متقاضی)، `Initiator Department` (کارکنان هم‌واحد)، `Employee`، `Department` و `Role` را تفکیک و استخراج می‌کند.
4. **آیا شرط‌ها قابل اجرا هستند؟** بله، موتور شرطی `asoud_erp/services/workflow_condition.py:1-40` و رزولور فیلدها در `workflow_condition_binding.py:215-265` مقادیر ارسالی فرم را بررسی کرده و شروط مقایسه‌ای را به صورت ایمن اجرا می‌کنند.
5. **آیا عملیات خودکار قابل انجام است؟** بله، برای درخواست‌های ۱۰ گانه، سیستم از طریق رجیستری `EXECUTORS` در `asoud_erp/services/form_execution/` پس از تأیید نهایی، اقدام به ساخت سند رسمی متناظر در ERPNext/HRMS می‌کند (مانند ساخت `Leave Application`, `Employee Advance`, `Attendance`, `Shift Assignment`).
6. **آیا نتیجه نهایی قابل ثبت است؟** بله، تابع `finish` در `asoud_erp/services/workflow_end.py:10-55` نتایج نهایی را در ۴ حالت استاندارد (`Completed`, `Rejected`, `Cancelled`, `Stopped`) در فیلد `status` و `ASOUD Workflow Activity` ثبت می‌کند.

---

### ۲۳. سایر ماژول‌ها و دوگانگی واژگان ماژول‌ها در سیستم

بررسی دقیق سورس‌کد نشان داد که دو واژگان کاملاً متفاوت و ناسازگار برای کلید ماژول‌ها (`module_key`) در بک‌اند و فرانت‌اند وجود دارد که موجب پیچیدگی و سردرگمی فنی شده است:

#### واژگان الف: تعریف گردش‌کار (`asoud_workflow_definition`)
در فایل تعریف DocType در مسیر:
`asoud_erp/asoud_erp/doctype/asoud_workflow_definition/asoud_workflow_definition.json` (خط ۲۰):
فیلد `module_key` از نوع `Select` با گزینه‌های زیر تعریف شده است:
- `Purchase` (خرید)
- `Accounting` (حسابداری)
- `Sales` (فروش)
- `Inventory` (انبار)
- `Support` (پشتیبانی)
- `HR` (منابع انسانی)

#### واژگان ب: الگوهای اسناد (`document_templates.py`)
در دیکشنری `MODULES` در فایل:
`asoud_erp/services/document_templates.py` (خطوط ۱۷-۴۰):
ماژول‌ها با کلیدهای زیر تعریف شده‌اند:
- `Finance` (مالی - حسابداری و خزانه‌داری)
- `Purchase` (خرید - تأمین کالا و خدمات)
- `Selling` (فروش - مدیریت فروش و مشتریان)
- `Stock` (انبار - مدیریت موجودی کالا)
- `HR` (منابع انسانی - کارکنان و حقوق)
- `Admin` (خدمات اداری - خدمات رفاهی و اداری)
- `IT` (IT و تجهیزات - تجهیزات و زیرساخت)


#### وضعیت انواع اسناد فعال در الگوها (`types`):
در `asoud_erp/services/document_templates.py:17-40`:
- **Finance:** دارای ۳ نوع سند است: `Journal Entry` با پرچم `enabled: True`، و اسناد `Receipt` و `Payment` با پرچم `enabled: False`.
- **Purchase:** دارای ۲ نوع سند است: `Material Request` با پرچم `enabled: True`، و `Purchase Order` با پرچم `enabled: False`.
- **Selling:** فاقد هرگونه سند هدف است: `"types": []` (خالی).
- **Stock:** فاقد هرگونه سند هدف است: `"types": []` (خالی).
- **HR:** فاقد هرگونه سند هدف است: `"types": []` (خالی).
- **Admin:** فاقد هرگونه سند هدف است: `"types": []` (خالی).
- **IT:** فاقد هرگونه سند هدف است: `"types": []` (خالی).

#### اثر در سمت اپلیکیشن (Flutter):
به دلیل این تناقض در سورس‌کد، فرانت‌اند ناچار شده است در چندین ویجت از کدهای نگاشت دستی و موقت استفاده کند:
1. در `flutter-asoud-erp/lib/features/workflows/presentation/widgets/stage_form_source_picker.dart` (خط ۲۷ و ۷۵):
   ```dart
   // خط ۲۷
   'Accounting' => 'Finance', 'Support' => 'Admin', _ => widget.initialModule
   // خط ۷۵
   'Finance' => 'Accounting', 'Admin' => 'Support', final key => key
   ```
2. در `stage_form_source_picker.dart` (خط ۱۸۱):
   ```dart
   return switch (key) {
     'Stock' => 'Inventory',
     'Accounting' => 'Finance',
     'Administration' || 'Support' => 'Admin',
     _ => key
   };
   ```
3. در `flutter-asoud-erp/lib/features/workflows/data/new_request_catalog.dart` (خطوط ۱۷۶-۱۸۳):
   تعریف دسته‌های نامتقارن برای برچسب‌گذاری:
   `'Accounting': 'مالی'`, `'Finance': 'مالی'`, `'Stock': 'انبار'`, `'Inventory': 'انبار'`, `'Selling': 'فروش'`, `'Sales': 'فروش'`.

---

## ۳. خروجی اجباری ۴۱: گزارش ارتباط با فرم‌ساز و منابع داده پویا/ایستا

این گزارش جامع، وضعیت دسترسی موتور گردش‌کار و فرم‌ساز به موجودیت‌ها و منابع داده پویا در مقایسه با فهرست‌های هاردکدشده (ایستا) را تشریح می‌کند:

| عنوان موجودیت / فیلد | نحوه واکشی (پویا / ایستا) | فایل و خط سورس‌کد | کنترل دسترسی و فیلترها | رفتار در خطای عدم وجود یا تغییر داده |
|---|---|---|---|---|
| فیلدهای فرم متصل (`ASOUD Form`) | پویا (از `ASOUD Form Revision`) | `asoud_erp/services/workflow_condition_binding.py:97-150` | بررسی وضعیت انتشار، فیلتر فیلدهای `hidden`، `permlevel > 0` و `sensitive` | در صورت تغییر یا حذف فیلد، خطای صریح در `validate_bindings` صادر می‌شود. |
| منابع انتخابی سیستم (`System Select`) | پویا با لیست مقاصد معین | `asoud_erp/services/request_lookup.py:17-45` | محدود به ۷ منبع مجاز: `cost_center`, `project`, `warehouse`, `branch`, `supplier`, `leave_type`, `delivery_location` با کنترل دفتر شرکت | در صورت غیرفعال بودن رکورد، از لیست فیلتر شده و در زمان ثبت خطا می‌دهد. |
| گزینه‌های فیلدهای پیوند (`Link Options`) | پویا از جداول اصلی Frappe | `asoud_erp/api/v1/forms.py:425-485` و `services/form_schema.py:15-30` | محدود به ۱۴ مدل در `SOURCES` و اعمال فیلتر دفتر و پرسنل متصل در `SCOPED_SOURCES` | در صورت نبود دسترسی یا نامعتبر بودن رکورد، خطای اعتبارسنجی بازگردانده می‌شود. |
| ماژول‌های مجاز الگوهای سند | **کاملاً ایستا (Hardcoded)** | `asoud_erp/services/document_templates.py:17-40` | دیکشنری ثابت پایتون شامل ۷ کلید ثابت (`Finance`, `Purchase`, `Selling`, `Stock`, `HR`, `Admin`, `IT`) | امکان افزودن ماژول دلخواه بدون دستکاری کد وجود ندارد. |
| موجودیت‌های مقصد سند (`NATIVE`) | **کاملاً ایستا (Hardcoded)** | `asoud_erp/api/v1/forms.py:32-35` | هاردکدشده در کد پایتون و محدود به `Journal Entry` و `Material Request` | ایجاد فرم برای سایر DocTypeهای ERPNext در فرم‌ساز امکان‌پذیر نیست. |
| فیلدهای مجاز نگاشت سند (`CHILDREN`) | **کاملاً ایستا (Hardcoded)** | `asoud_erp/api/v1/forms.py:34-36` | فقط فیلدهای معین جداول حساب‌ها و اقلام مجاز به نگاشت در فرم هستند | فیلدهای سفارشی (Custom Fields) اضافه شده به سند ERPNext شناسایی نمی‌شوند. |
| انواع انتساب مرحله (`ASSIGNMENT_TYPES`) | **کاملاً ایستا (Hardcoded)** | `asoud_erp/services/workflow_stage_policy.py:32-35` | محدود به ۶ حالت: `Role`, `Department`, `Employee`, `Initiator`, `Initiator Department`, `Direct Manager` | سایر الگوهای انتساب سازمانی (مانند مدیر بخش، مدیر پروژه) پشتیبانی نمی‌شوند. |

---


## استثناهای اتصال و تغییر نسخه

A5 دربارهٔ ثبات source_revision توضیح می‌دهد، ولی runtime گراف زنده را می‌خواند (A1-007/A6-012). نسخهٔ فرم و نسخهٔ گراف دو مفهوم متفاوت‌اند. همچنین ارجاع‌های جدول HR قابلیت اتصال در کد را نشان می‌دهند؛ نقص فرم Document می‌تواند همان قابلیت را در ثبت عملی متوقف کند. رفع tuple در 4c4d4e7/de979be و رفع request_key در 3244ed2 طبق بازبین در PR #61 در انتظار ادغام است.

حذف فیلد، تغییر نوع، محرمانگی و منابع previous-stage با شناسهٔ پایدار و guaranteed_predecessors در متن بالا مستندند. به ادعای کلی منع تغییر همهٔ رکوردهای مرتبط نباید تعمیم داد: Link Record و رکورد خروجی خودکار مسیرهای مجزای مستند در A4 هستند.

