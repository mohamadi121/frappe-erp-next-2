# ۴۲ — موتور اجرا، کارتابل و پایداری

تاریخ: ۱۴۰۵/۰۸/۲۳ = 2026-11-14؛ مبنای ممیزی: اپ `c324e9e`، بک‌اند `448855f`. این سند تلفیق شواهد پذیرفته‌شدهٔ A1 تا A6 با تقدم REVIEW-NOTES.md است. بررسی کد یا اجرای مجدد تست در A7 انجام نشده است. ارجاع فایل و خط، مربوط به مبنای ممیزی است.

## داوری چرخهٔ اجرا

چرخهٔ اصلی سروری است و به بازبودن اپ وابسته نیست. تکمیل وظیفه با قفل و وضعیت Open مانع اقدام دوباره می‌شود؛ بازگرداندن نتیجهٔ قبلی در retry شبکه پیاده نشده است. نمونه current_stage منفرد دارد؛ وجود چند خط در Canvas اثبات اجرای چندتوکنی موازی نیست. snapshot فرم/انتظار/رسید خودکار، جای snapshot کامل گراف را نمی‌گیرد.

تصحیح ارجاع داخلی A6: API ارسال فرم مطابق امضای مستند A1 و A5، forms.submit_form در forms.py:636 است؛ forms.submit_form_entry:350 در روایت A6 با فهرست API سازگار نیست و API تأییدشده محسوب نمی‌شود. اعلان‌های Frappe در Notification Log طبق A1 مستندند؛ جدول ASOUD Notification در روایت A6 در مدل ۱۱ DocType تأیید نشده است. روایت تخصیص شرکتی A6 نیز شامل همهٔ مسیرها نیست؛ مسیر قدیمی _users_for_roles در A1-011 فاقد فیلتر شرکت گزارش شده است.

## ۲. ردیابی چرخه حیات ۱۳ مرحله‌ای موتور اجرا (بخش ۲۴ و خروجی ۴۲)

موتور اجرای فرایندساز آسود بر بستر اپلیکیشن Frappe توسعه یافته و چرخه حیات اجرای درخواست‌ها و فرم‌ها شامل ۱۳ مرحله به شرح فنی زیر است:

### مرحله ۱: ثبت درخواست یا سند (Request/Document Submission)
- **فایل و تابع**:
  - برای درخواست‌های عمومی: `asoud_erp/api/v1/workflow_request.py:578` در تابع `create_request`.
  - برای ارسال فرم‌های پویا: `asoud_erp/api/v1/forms.py:636` در تابع `submit_form`.
- **API مرتبط**:
  - `POST /api/method/asoud_erp.api.v1.workflow_request.create_request`
  - `POST /api/method/asoud_erp.api.v1.forms.submit_form`
- **عملیات دیتابیس**:
  - درج در `tabASOUD Workflow Request` با وضعیت `Submitted` و کلید یکتای `request_id` و اثرانگشت داده‌ها `request_fingerprint`.
  - ذخیره مقادیر در قالب JSON در فیلد `values_json` و پیوست‌ها در `attachments_json`.

### مرحله ۲: تشخیص گردش‌کار (Workflow Routing & Resolution)
- **فایل و تابع**:
  - `asoud_erp/services/workflow_submission_source.py:125` در تابع `route(form, revision, submitted=None)`.
- **منطق اجرا**:
  - خواندن تعاریف غیربایگانی متصل به فرم از `tabASOUD Workflow Definition` با فیلتر `source_form`.
  - استخراج تنظیمات مسیر از مراحل شروع با فراخوانی `routing_configs(names, current=True)`.
  - ارزیابی گره‌های شرطی متصل به شروع (`entry_condition`) برای مسیرهای `Conditional` و انتخاب بر اساس اولویت مسیرها در `choose_route`.

### مرحله ۳: ایجاد نمونه اجرا (Workflow Instance Creation)
- **فایل و تابع**:
  - `asoud_erp/api/v1/workflow_runtime.py:708` در تابع `start_workflow_instance`.
- **منطق و دیتابیس**:
  - اعتبارسنجی عنوان (۳ تا ۱۴۰ کاراکتر)، بررسی وضعیت تعریف (`status == 'Active'` و `readiness_status == 'Ready'`).
  - کنترل Idempotency از طریق بررسی `request_id` در سوابق `tabASOUD Workflow Activity`.
  - درج سند در `tabASOUD Workflow Instance` با وضعیت `Running`، ثبت `started_by` و زمان `started_on`.

### مرحله ۴: شروع مرحله اول (Start Stage Activation)
- **فایل و تابع**:
  - `asoud_erp/api/v1/workflow_runtime.py:858-892` در `start_workflow_instance`.
- **منطق**:
  - شناسایی مرحله نوع `Start` از داک‌تایپ `ASOUD Workflow Stage` با فیلتر `stage_type = 'Start'`.
  - ثبت رخداد شروع در `tabASOUD Workflow Activity` با اکشن `Workflow Started`.
  - واکشی مرحله بعدی از طریق `_next_stage(instance, start)`.
  - انتساب `instance.current_stage = start` و فراخوانی `_activate_stage(instance, stage)`.

### مرحله ۵: انتقال به مرحله بعد (Transition Routing)
- **فایل و تابع**:
  - `asoud_erp/api/v1/workflow_runtime.py:239` در تابع `_next_stage(instance, current_stage, action=None)`.
- **منطق**:
  - واکشی مسیرهای خروجی از `tabASOUD Workflow Transition` با فیلتر `from_stage = current_stage` مرتب‌شده بر اساس `sequence_no asc`.
  - تطبیق اکشن درخواستی با `condition_json.action` یا `transition_label`.
  - کنترل معتبر بودن مرحله مقصد در `tabASOUD Workflow Stage` و جلوگیری از اتصال اشتباه به `Start` یا به خود مرحله.

### مرحله ۶: تخصیص مسئول (Assignee Resolution)
- **فایل و تابع**:
  - برای اکشن‌های قراردادی V1: `asoud_erp/services/workflow_user_action.py:85` در تابع `users_for(stage, instance)`.
  - برای مراحل تأیید و وظایف کلاسیک: `asoud_erp/api/v1/workflow_runtime.py:137` در تابع `_users_for_stage(stage, instance)`.
- **قواعد تخصیص**:
  - بر اساس نقش (`Role`)، کاربر مشخص (`Employee`)، واحد سازمانی (`Department`)، مدیر مستقیم (`Direct Manager` از فیلد `reports_to`)، یا فرد موضوع درخواست (`Subject` / `Form Employee`).
  - فیلتر روی کاربران فعال سیستم، حذف کاربران غیرفعال، و اعتبارسنجی تعلق به شرکت مربوطه از طریق `company_access(company, user)`.

### مرحله ۷: ایجاد وظیفه در کارتابل (Task Generation)
- **فایل و تابع**:
  - `asoud_erp/api/v1/workflow_runtime.py:503-530` در تابع `_activate_stage`.
- **دیتابیس و اعلان**:
  - درج رکوردهای `tabASOUD Workflow Task` با وضعیت `Open`، اختصاص به کاربر (`assigned_to`)، محاسبه مهلت (`due_on`) و زمان یادآوری (`reminder_on`).
  - در حالت اقدامات مشترک (`Shared`)، تنظیم وضعیت اولیه روی `Awaiting Claim`.
  - ارسال اعلان سیستمی با فراخوانی `_notify_user` و درج در سیستم اعلان Frappe (`Notification Log` طبق A1).

### مرحله ۸: دریافت اقدام انسانی (Human Decision & Submission)
- **فایل و تابع**:
  - `asoud_erp/api/v1/workflow_runtime.py:1367` در متد Whitelisted به نام `complete_workflow_task`.
  - ذخیره پیش‌نویس: `asoud_erp/api/v1/workflow_runtime.py:1234` در `save_workflow_task_draft`.
  - مدیریت اقدامات پیشرفته: `asoud_erp/services/workflow_user_action.py:361` در متد `handle`.
- **اکشن‌های مجاز**:
  - `Approve`, `Reject`, `Return`, `Complete`, `Claim`, `Follow Up`, `Blocked`, `Reassign`.
  - اعتبارسنجی مالکیت وظیفه توسط `_assert_task_owner(original)`، اعتبارسنجی مقادیر فرم تکمیلی و فیلدهای درون‌خطی.

### مرحله ۹: ارزیابی شرط و شاخه‌بندی (Condition Evaluation)
- **فایل و تابع**:
  - `asoud_erp/api/v1/workflow_runtime.py:394-467` در `_activate_stage`.
  - موتور شروط V2: `asoud_erp/services/workflow_condition.py:112` در `evaluate_group` و `asoud_erp/services/workflow_condition_binding.py`.
- **منطق**:
  - حل مقادیر مبدأ فیلدها از فرم اصلی، مقادیر مراحل قبلی، یا موجودیت سند (`resolver`).
  - محاسبه منطقی شروط (عملگرهای Equals, GreaterThan, LessThan, In, Contains و ترکیب‌های AND/OR).
  - انتخاب مسیر خروجی بولین از طریق `select_boolean_transition` و فعال‌سازی فوری گره مقصد بدون توقف.

### مرحله ۱۰: اجرای اقدام خودکار (System / Automatic Action Execution)
- **فایل و تابع**:
  - زمان‌بندی: `asoud_erp/services/automatic_action_runtime.py:485` در تابع `schedule`.
  - اجرای پس‌زمینه: `asoud_erp/services/automatic_action_runtime.py:533` در تابع `run(execution)`.
  - کرون دیسپچر: `asoud_erp/services/automatic_action_runtime.py:594` در `dispatch()`.
- **مکانیزم فنی**:
  - تولید رسید اجرای یکتا در `tabASOUD Action Execution` با شناسه هش SHA-256.
  - تفویض اجرا به کارگر صف Frappe (`frappe.enqueue`) با کاربر سیستمی `service_user(_company(instance))`.
  - هدایت جریان پس از موفقیت به مسیر `Success` یا پس از اتمام بودجه تلاش مجدد به `Error`.

### مرحله ۱۱: اجرای انتظار (Wait Stage Execution)
- **فایل و تابع**:
  - ورود به انتظار: `asoud_erp/services/workflow_wait.py:152` در تابع `schedule(instance, stage, config)`.
  - اجرای سررسید: `asoud_erp/services/workflow_wait.py:176` در تابع `run(name)`.
  - کرون بررسی دوره‌ای: `asoud_erp/services/workflow_wait.py:221` در `dispatch()`.
- **دیتابیس**:
  - ثبت زمان سررسید به UTC در ستون ایندکس‌شده `wait_due_utc` و اطلاعات پیکربندی در `wait_snapshot_json` روی رکورد `ASOUD Workflow Instance`.

### مرحله ۱۲: پایان فرایند (Workflow Termination)
- **فایل و تابع**:
  - `asoud_erp/services/workflow_end.py:8` در تابع `finish(instance, stage, *, previous_stage, source_task=None)`.
- **منطق**:
  - اخذ قفل ردیف نمونه با `for_update=True`، اعتبارسنجی عدم وجود مسیر خروجی از مرحله پایان.
  - تعیین وضعیت نهایی (`Completed`, `Rejected`, `Cancelled`, `Failed`) بر اساس پیکربندی گره پایان یا تصمیم مرحله رد پیشین.
  - لغو کلیه وظایف باز باقیمانده (`tabASOUD Workflow Task.status = 'Cancelled'`) با ثبت زمان خاتمه.
  - ثبت رویداد `پایان عملیات` در جدول `tabASOUD Workflow Activity` با لاگ تغییرات قبل و بعد.

### مرحله ۱۳: ثبت سوابق و تاریخچه (Activity & Audit Logging)
- **فایل و تابع**:
  - `asoud_erp/api/v1/workflow_runtime.py:95` در `_record_activity` و `asoud_erp/services/workflow_history.py`.
- **دیتابیس**:
  - درج ردیف در `tabASOUD Workflow Activity` شامل شناسه نمونه، مرحله، وظیفه، کاربر اقدام‌کننده، شرح اقدام، و مستندات تغییر یافته در فیلد JSON به نام `change_json`.

---

## ۳. ممیزی جامع کارتابل سازمانی (بخش ۲۷)

### ۱. چرخه ایجاد و تخصیص وظیفه
- وظیفه کارتابل با ساختار داک‌تایپ استاندارد `ASOUD Workflow Task` با پیشوند `WFT-{YYYY}-{#####}` تعریف شده است.
- در زمان فعال‌سازی مرحله در `workflow_runtime.py:504-521`، به ازای هر کاربر واجد شرایط یک وظیفه با وضعیت `Open` ثبت می‌شود.
- در مراحل از نوع اقدام تیمی/مشترک (`Shared delivery`)، اکشن وظیفه روی `Awaiting Claim` قرار می‌گیرد تا اولین کاربر با زدن دکمه «دریافت اقدام»، آن را به نام خود اختصاصی کند.

### ۲. نمایش در کارتابل و دسترسی کاربران
- API دریافت وظایف کارتابل: `asoud_erp.api.v1.workflow_runtime.list_my_workflow_tasks` با پارامترهای `status` و `start` و `paged`.
- شرط SQL استخراج وظایف در `workflow_runtime.py:965` به صراحت `assigned_to = %(user)s` را با گارد دسترسی بخشنامه‌ها و دستورات ترکیب می‌کند.
- سمت کلاینت در `CartablePage` (`cartable_page.dart:79`)، چهار گروه وظایف (`Open`, `Completed`, `Rejected`, `Cancelled`) را به همراه نمونه‌های ارسالی کاربر (`getMyInstances`) دریافت و در تب‌های چهارگانه (دریافتی، ارسالی، در جریان، بایگانی) دسته‌بندی می‌کند.

### ۳. پیشگیری از وظایف تکراری
- در زمان شروع فرایند، وجود نمونه فعال بررسی می‌شود.
- در سناریوی تأیید اشتراکی (`approval_mode == "Any"` در `workflow_runtime.py:1554`)، به محض اینکه اولین کاربر تأیید را ثبت کند، بقیه وظایف باز آن مرحله با کوئری مستقیم به وضعیت `Cancelled` تغییر می‌یابند تا از تصمیم‌گیری موازی جلوگیری شود.
- در اکشن‌های خودکار، رسید با کلید یکتای مشتق از هش SHA-256 (`execution_id`) در دیتابیس درج می‌شود که از ایجاد وظیفه خودکار تکراری ممانعت می‌کند.

### ۴. ثبت تاریخچه و سوابق اقدام
- هر عملیات انجام‌شده (تأیید، رد، بازگشت، پیش‌نویس، واگذاری) بلافاصله در داک‌تایپ `ASOUD Workflow Activity` ثبت می‌شود و در تایم‌لاین وظیفه (`WorkflowActivityTimeline`) در دسترس است.

---


### ۳. ممیزی تکرار درخواست و قابلیت بازپخش (Replay & Idempotency)
- در ثبت درخواست (`create_request`)، کلید `request_id` و هش محتوا (`request_fingerprint`) در سطح دیتابیس کنترل شده و از ثبت درخواست تکراری جلوگیری می‌کند.
- **نقص شناسایی‌شده (A6-010)**: در تکمیل وظایف (`complete_workflow_task`)، هیچ کلید Idempotency وجود ندارد. در شرایط ناپایداری اینترنت موبایل، در صورتی که پاسخ اول به کلاینت نرسد و برنامه درخواست را مجدداً ارسال کند، سرور با خطای ۴۱۷ (`Workflow task has already been completed`) پاسخ می‌دهد که باعث نمایش خطای نامفهوم به کاربر می‌شود.

---

## ۶. ممیزی پایداری، همزمانی و تاب‌آوری (بخش ۳۰)

### ۱. تحلیل قفل‌های همزمانی دیتابیس (Concurrency & Deadlocks)
- **ایراد بحرانی کالیبره‌شده (A6-001)**: در متد `services/workflow_submission_source.py:route()`، بر روی تمام تعاریف گردش‌کار مرتبط با فرم دستور `SELECT ... FOR UPDATE` اجرا شده و متعاقب آن تابع `routing_configs(current=True)` فراخوانی می‌شود که تا سقف ۴۰,۲۰۱ ردیف از مراحل جدول `tabASOUD Workflow Stage` را برای هر ثبت فرم به صورت انحصاری قفل می‌کند. این امر باعث گلوگاه وحشتناک همزمانی، توقف درخواست‌های موازی و خطاهای `Lock wait timeout` و `Deadlock` در دیتابیس MariaDB می‌شود.

### ۲. ممیزی زمان‌بند و صف‌های پس‌زمینه (Scheduler & Background Jobs)
- **ایراد کالیبره‌شده زمان‌بند (A6-002)**: در `services/workflow_wait.py:dispatch()`، زمان‌بند کرون سرور در هر دقیقه کلیه نمونه‌های در حال انتظار دیتابیس را بدون فیلتر کردن زمان سررسید (`wait_due_utc <= now`) به صف Redis/RQ می‌فرستد (`frappe.enqueue`). این رفتار باعث بمباران صف و مصرف بی‌مورد منابع پردازشی و رم سرور در هر ۶۰ ثانیه می‌شود.

### ۳. رفتار در زمان تغییر تعاریف و نسخه‌های قدیمی (Version Incompatibility)
- **ایراد پایداری (A6-012)**: زمانی که تعریف یک فرایند در Designer ویرایش می‌شود، تغییرات مستقیماً روی رکوردهای `tabASOUD Workflow Stage` و `tabASOUD Workflow Transition` ذخیره می‌شوند و نسخه‌بندی ایزوله‌ای برای اجرای نمونه‌های قبلی وجود ندارد. اگر مدیری یک انتقال را حذف یا بازطراحی کند، نمونه‌های جاری فعال که در آن مرحله قرار دارند در گام بعدی به دلیل نیافتن انتقال متوقف شده و با خطای `Workflow has no executable stage` مسدود می‌شوند.

---

## اصلاح تفسیر پایداری و شواهد تکمیلی

قفل‌های FOR UPDATE قطعی در سورس‌اند؛ سقف 40201 تعداد واقعی ردیف قفل‌شده نیست و هیچ benchmark زنده در A7 وجود ندارد. wait dispatch در commit ممیزی ایراد دارد و با b16f78e در review اصلاح شده است؛ ملاحظهٔ Recalculate باید در تست پذیرش حفظ شود. Stopped، tuple، request_key و برچسب Wait نیز طبق 45 رفع در انتظار ادغام دارند.

حفاظت دادهٔ اصلی در روایت شروع، ناظر به ثبت رفرنس/آغاز است؛ مراحل ویرایشی یا خودکار ممکن است طبق مجوز داده را تغییر دهند. ادعای «Claimed» در شرح A3 نباید با vocabulary وضعیت تسک اشتباه شود: وضعیت‌های شمای تسک Open/Completed/Rejected/Cancelled هستند و Claim/Awaiting Claim در قرارداد اکشن تفسیر می‌شوند. وضعیت/اکشن دقیق در اجرای زنده بررسی نشده است.

سایر ریسک‌های runtime: بازگشت به تأیید دارای فرم تکمیلی A3-002؛ پیش‌نویس خالی قرارداد V1 A3-014؛ منع تکرار رسید خودکار A6-006؛ مسیر خطای محدود به User Task در A6-007؛ race لغو و رسید خودکار A6-014. تمام متن و روش اثبات آن‌ها در 45 حفظ شده است.

