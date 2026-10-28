# Changelog

## Unreleased

- Added a single real-site lifecycle matrix for five HR documents and five role/scope cases, including approval, existing numbering, frozen print and replay. Shared role/company/task denials now use Persian PermissionErrors without field details. CI includes the matrix. Deployment: restart workers; no migration.

- First-office HR status and provisioning share a company transaction lock with a three-second wait; busy status raises a Persian pending error instead of a false empty lead. Repeated creation explicitly returns `idempotent_replay: true` and the original username without changing credentials. Deployment: restart workers; no migration.

- All five HR final prints flag missing historical letterhead metadata and render legacy finals without a header; they never load the current header. Hiring finalization now freezes letterhead metadata. Deployment: restart workers; no migration or legacy rewrite.

- Hiring payroll preserves native HRMS effective-date formula previews and adds explicit missing-assignment/component reason codes to immutable payroll rows. Deployment: restart workers; no migration.

- Administrator login hints now require the essential profile before office creation and setup; disabled accounts and temporary passwords retain priority. Existing integration assertions now complete the fiscal/bootstrap prerequisites before expecting home. Deployment: restart workers; no migration.

- First HR lead provisioning returns Persian errors naming missing/duplicate fields and weak temporary passwords, checks native password strength before writes, and accepts omitted optional HTTP arguments for validation. Added real-site coverage to CI. Deployment: restart workers; no schema migration.

- Employment certificate workflow routing: templates support workflow binding; certificate finalization submits to the configured request workflow, tracks real workflow lifecycle events, and allocates official certificate numbering only upon final approval. In the absence of a configured workflow, the direct HR operational issuance policy applies immediately with Jalali date and letterhead snapshotting. No schema migration required; restart backend workers.
- Employment contract workflow finalization, atomic Jalali numbering, introduction letter replay/snapshot lock, Playwright API specs for all five HR documents, and malformed/oversized input validation matrix across document save endpoints. Deployment: restart workers; no migration.

- HR document privacy: hiring/salary-order detail and print mask payroll for HR-only users; certificate reads and retries strip nested payroll values when unauthorized or salary is disabled. HR Manager alone no longer grants certificate payroll access. HTTP privacy coverage is included in the API script (duplicate script key removed). Deployment: restart workers; no migration.

- Certificate updates lock their entry, reject absent/stale revisions and refuse changes to finalized documents or another company’s entry. Deployment: restart workers; no migration.

- Certificate and introduction-letter print rendering escapes literal clause text and certificate metadata. Deployment: restart workers; existing frozen HTML requires a separate explicit migration.

- First-office input validation imports without a Frappe installation; runtime hooks load Frappe only when called. Deployment: restart workers; no migration.

- Employment Contracts template builder and issuance API: versioned contract articles/clauses stored via ASOUD Form/Revision, insert-field drawer catalog from real data sources (personnel, company, contract, payroll gated by payroll permission), repeating salary items calculation with explicit missing state («اطلاعات موجود نیست»), contracts list with server-side Persian/Arabic/digit search, draft saving, finalization with Jalali-year series numbering (CNT-1405-#####), immutable revision snapshots, and A4 RTL print payload with draft banner («پیش‌نویس ـ فاقد اعتبار نهایی»). See `docs/api/employment_contracts.md`. No schema migration required; restart backend workers.
- گواهی اشتغال مستقل: پیاده‌سازی کامل API قالب نسخه‌دار و صدور/فهرست/چاپ گواهی‌های اشتغال به کار با آزمون‌های یکپارچگی افزوده شد. استقرار نهایی به restart نیاز دارد.
- اقلام حقوق حکم استخدام، شامل مزایا و کسورات فرمولی، از پیش‌نمایش بومی HRMS در تاریخ اجرا محاسبه می‌شوند؛ فیشی ذخیره نمی‌شود و منبع ناموجود همچنان «اطلاعات موجود نیست» است. بدون migration.

- حکم استخدام از گردش‌کار آمادهٔ متصل به نسخهٔ قالب ارسال می‌شود؛ فقط تکمیل واقعی گردش‌کار حکم را شماره‌دار و نهایی می‌کند. بدون گردش‌کار، سیاست صدور مستقیم منابع انسانی اعمال می‌شود. ارسال با قفل و شناسهٔ یکتا تکرارپذیر است؛ قالب و مبالغ ثبت‌شده حفظ می‌شوند. بدون migration.

- احکام استخدام: کاتالوگ واقعی اقلام حقوق با دسترسی حقوق، کنترل منبع قالب و snapshot سروری ردیف‌های نسخهٔ منتشرشده در تاریخ اجرا؛ مبالغ مشتری نادیده گرفته می‌شوند. تاریخ میلادی چاپ به شمسی تبدیل می‌شود. بدون migration.

- احکام استخدام: چرخه کامل قالب (ذخیره و انتشار پیش‌نویس تغییرناپذیر)، صدور حکم، ثبت پیش‌نویس، بررسی، دریافت و چاپ A4 با نوار پیش‌نویس و سربرگ سازمان افزوده شد. شماره‌گذاری رسمی، نرمال‌سازی جست‌وجو و کنترل مجوز شرکت پیاده‌سازی شدند. استقرار: فقط restart، بدون تغییر schema یا migration.

- منابع دادهٔ حکم استخدام: endpointهای صفحه‌بندی‌شدهٔ انتخاب پرسنل و snapshot حقوق در تاریخ اجرا افزوده شد. مقدار حقوق ناموجود صریحاً «اطلاعات موجود نیست» است و هرگز صفر نمی‌شود. استقرار: فقط restart؛ ثبت، نسخه‌بندی و نهایی‌سازی حکم در این تغییر افزوده نشده است.
- Introduction-letter workflow submission sends only fields declared by the selected workflow form and retains required-field validation. Request references use the existing company/owner permission policy so operational HR users can submit their own requests without an Employee role.

- Introduction-letter issuance uses the existing request workflow and completion/rejection events when a workflow is configured; without a workflow it follows the current HR direct-issuance policy. Official numbers use the shared Jalali request-numbering pattern. Sent/final snapshots cannot be overwritten, and final print payloads remain frozen. Restart workers to load the lifecycle hook; no schema migration. New workflow code and tests were not run, as requested by the owner.

- Introduction letters use Employee.employee_number for personnel codes in options, snapshots and search, with an empty value when no code exists.

- Personnel introduction letters (`docs/api/personnel_introduction_letters.md`): versioned template builder and HR issuance API (`personnel_introduction_letters.get_template`, `save_template_draft`, `publish_template`, `get_employee_options`, `list_letters`, `get_letter`, `save_draft`, `finalize_letter`) with stable placeholder tags, server-side normalized search, idempotent draft and finalize handling, official document numbering (`INTRO-.YYYY.-.#####`), and immutable snapshotting.
- احکام افزایش یا تغییر حقوق و مزایا (`docs/api/salary_change_orders.md`): چرخه کامل قالب ۶ ماده‌ای با فرم‌ساز موجود و شناسه‌های پایدار، جدول مقایسه اقلام حقوق قبلی و جدید با محاسبه خالص اختلاف و درصد تغییر، عدم تغییر حقوق زنده در زمان پیش‌نویس، کنترل دسترسی تفکیک‌شده (طراح قالب / صادرکننده HR / مجری حقوق)، تأیید دومرحله‌ای و اعمال مجزا بر احکام ساختار حقوقی (`Salary Structure Assignment`) با شناسه عملیات تکرارپذیر (idempotency) و ثبت ردپا (audit trail)، وضعیت تفکیک‌شده تأیید و اعمال حقوقی، و فرمت چاپ A4 با نوار پیش‌نویس.

- First-office setup can complete without provisioning an HR account. Saved office, administrator/company access and active fiscal year remain required. No existing accounts or permissions change; deploy matching Flutter flow and restart backend workers. No schema migration required. Tests not run at user request.

- Native organizational unit descriptions: optional validated `save_unit.description` and `list_units.description`, persisted as `Department.asoud_description`; omitted updates preserve text. Deployment: `bench migrate` (idempotent patch `v0_18.add_department_description`, install/migrate Custom Field), restart, then release matching inline forms. No unit/position IDs or hierarchy are rewritten; permissions and revisions are unchanged.

- Organization localization: read/preview responses include Persian display names for known standard Department and position titles. Native IDs, raw titles, links and revisions are unchanged; unknown/custom titles are preserved. No new schema or migration for this change. Deploy with the matching Flutter display/fallback dictionary; see `docs/api/organization-localization.md`.

- Account-only first HR lead and final bootstrap confirmation (`docs/api/first-office-bootstrap.md`): native User/HR Manager/Company User Permission, optional email, native username login, 8–128-character temporary password with forced first-login change; no Employee or Party Profile. Internal non-deliverable identities are excluded from email recovery and outgoing mail. Deployment: `bench migrate` (new `first_hr_user` and `bootstrap_completed`, patch `v0_18.add_first_office_bootstrap`), restart workers, then release Flutter. Username login is enabled at provisioning. Marked first offices resume until final confirmation. No tests/site execution performed at user request.

- Login resumes `setup-first-office` for a system administrator whose marked first office has no enabled linked Fiscal Year. Uses existing bootstrap marker and native fiscal records; no schema migration. Matching Flutter fiscal setup screen must be released with this route.

- Office save validates optional personal/legal identity checksums, 09 mobile numbers and ten-digit postal codes before Company writes; Persian digits are supported, bare website domains gain HTTPS. No schema migration or rewrite of existing records; deploy alongside the matching office form validation.

- اصلاح: `sync.execute_mutation` اقدام‌های دستور (`issue`، `start`، `report`، `review`، `transfer`، `close`) را با «METHOD_NOT_ALLOWED» رد می‌کرد و دستور صادرشده از اپ پیش‌نویس می‌ماند؛ این نام‌ها اکنون مجازند. بدون مهاجرت؛ فقط restart.

- اصلاح: `hr_onboarding.register_personnel` برای مدیر کل سیستم (بدون نقش مدیر منابع انسانی) با «No permission for Employee» رد می‌شد؛ نوشتن‌های پرسنلی پس از کنترل نقش برای مدیر کل با دسترسی سیستمی انجام می‌شود. در `create_first_office` شکست rollback دیگر خطای اصلی را با «SAVEPOINT does not exist» جایگزین نمی‌کند. بدون مهاجرت؛ فقط restart.

- اصلاح: ورود (`POST /api/method/login`) حساب دارای رمز موقت با کد ۴۰۳ رد می‌شد و تغییر اجباری رمز هرگز شروع نمی‌شد؛ `login` به فهرست مجاز نگهبان نشست افزوده شد. بدون مهاجرت؛ فقط restart.

- Organization management: added read-only `preview_delete_position` with company, role, document and revision checks; chart saves now block cascading removal of reporting children as well as occupants/history. Deploy backend before the matching Flutter inline editor; restart workers, no new schema or migration.

- ورود، راه‌اندازی اولیه، مدیر کل سیستم، نقش‌ها و ثبت پرسنل (جزئیات: `docs/api/login-onboarding.md`، ممیزی: `docs/login-onboarding-audit.md`): `session.login_state/logout/select_office`؛ سرویس یگانهٔ `account_security.change_password` با سیاست رمز، محدودیت تلاش، ابطال نشست‌های دیگر و الزام تغییر رمز موقت در سمت سرور (`before_request`)؛ بازیابی رمز با کد یک‌بارمصرف هش‌شده (فقط وقتی ایمیل خروجی تنظیم است)؛ `onboarding.create_first_office` (یک‌بار، با قفل) و `save_admin_profile`؛ مدیر کل سیستم با نقش `System Manager` شناخته می‌شود، بدون پرونده پرسنلی می‌تواند دستور بدهد و گزارش کار بفرستد و آخرین مدیر کل قابل حذف/غیرفعال‌سازی نیست؛ مجوز ساخت دفتر مستقل از مدیریت دفتر (نقش `ASOUD Office Creator`)؛ نقش‌های دفتری (`ASOUD Office Role Assignment`) و `role_access.assign_role/unassign_role` با جلوگیری از ارتقای دسترسی (`ASOUD Role Assigner`)؛ کاتالوگ مجوز با ماژول کامل منابع انسانی و سه سطح ساده/متوسط/پیشرفته با اقدامات واقعی (`advanced_grants`)؛ `hr_onboarding.register_personnel/bootstrap_hr_lead/issue_temporary_password`؛ دفتر ممیزی افزایشی `ASOUD Security Audit`. Deployment: `bench --site <site> migrate` (DocTypeهای تازه `ASOUD Security Audit`، `ASOUD Account State`، `ASOUD Account Token`، `ASOUD Office Role Assignment`؛ فیلدهای تازه در `ASOUD Settings`، `ASOUD Company Setup`، `ASOUD Role Definition`، `ASOUD Party Profile`، `ASOUD Work Report`؛ پچ `v0_18.ensure_security_roles_and_backfill`)، سپس restart برای بارگذاری هوک‌های تازه (`doc_events` کاربر، `before_request`، `on_login`). رمز با الگوریتم بومی فریپه ذخیره می‌شود (Argon2id پیاده نشده)؛ تأیید موبایل/ایمیل پیاده نشده است.

- ده قالب خام موجود منابع انسانی به فهرست فرم‌های هر شرکت اضافه می‌شود. `open_builtin` فقط یک نمونه ثابت برای هر قالب و شرکت ایجاد می‌کند؛ `remove_builtin` مخصوص مدیر سیستم است و نسخه‌ها و ثبت‌های قبلی را حفظ می‌کند. هیچ گردش‌کار یا سند بومی به‌صورت ضمنی ایجاد نمی‌شود. استقرار: کد و بسته JSON را قبل از اپ جدید به‌روز و سرویس را restart کنید؛ این تغییر به مهاجرت تازه نیاز ندارد.

## 0.17.0 - 2026-10-24

Deployment: run `bench --site <site> migrate` (new `native_status` options `Needs Review` and `Voided`, patch `v0_15_3.normalize_native_review_status`), then restart so the new `doc_events` in `hooks.py` load. The certificate needs WeasyPrint on the server and a default Letter Head on the company.

- ابطال و صدور مجدد سند اجراشده: مدیر منابع انسانی (فقط `HR Manager`) با نوشتن دلیل، سند ساخته‌شدهٔ درخواست را ابطال می‌کند (`void_native_document`) و سپس می‌تواند با `reissue_native_document` سند تازه بسازد. سند ثبت‌شده با Cancel ابطال می‌شود، پیش‌نویس و تردد هرگز حذف نمی‌شوند (توضیح روی سند و ثبت در درخواست)، رویداد آموزشی هرگز لغو نمی‌شود. وضعیت `native_status = Voided`، نوار اجرا «سند ابطال شد»، فعالیت‌های `Voided`/`Reissued` با دلیل، کاربر و زمان. کلیدهای افزوده در `execution`: `can_void`، `can_reissue`، `void`. ابطال تسویه حساب تاریخ پایان همکاری قبلی را برمی‌گرداند و بیانیهٔ نهایی را مثل مصاحبه ابطال می‌کند؛ ابطال ثبت‌نام آموزشی ردیف شرکت‌کنندهٔ دورهٔ پیش‌نویس را برمی‌دارد. هرجا اثر قبلی صادقانه برگشت‌پذیر نیست (تردد، پیش‌نویس شیفت، مصاحبهٔ خروج پیش‌نویس، دورهٔ ثبت‌شده) `can_reissue` نادرست است و `execution.void.reissue_blocked` دلیل فارسی را می‌دهد. Deployment: `bench --site <site> migrate` (گزینهٔ تازهٔ `Voided` در `native_status`).

- اصلاح اقدام خودکار قدیمی (تغییر وضعیت و ایجاد سند): وقتی `asoud_workflow_service_user` در تنظیمات سایت نیست، اقدام قدیمی مانند قبل اجرا می‌شود و درخواست به‌جای «ناموفق» تکمیل می‌شود (این رفتار در ادغام ۲۰ مهر از دست رفته بود). اقدام نسخهٔ ۲ همچنان به کاربر سرویس نیاز دارد. بدون نیاز به مهاجرت یا تنظیم جدید.

- اجرای مرخصی، مأموریت و اضافه‌کار پس از تأیید: `leave_application` پس از تأیید نهایی Leave Application را با مانده واقعی HRMS (`get_leave_details`) ثبت و submit می‌کند (کمبود مانده، نبود تخصیص، هم‌پوشانی و تأییدکننده تنظیم‌نشده با پیام فارسی رد می‌شوند)؛ `mission` یک Attendance Request با دلیل `On Duty` (بدون احتساب تعطیلات) ثبت و submit می‌کند و فقط اگر روز اول یا آخر تعطیل باشد یا روزی کاری حضور، مرخصی یا درخواست حضور داشته باشد هیچ سندی نمی‌سازد (تعطیلی‌های میانی از حضور کنار گذاشته می‌شوند) و نتیجه «نیازمند بررسی» است؛ `overtime` فقط نتیجه «نیازمند بررسی» با تاریخ و مدت تأییدشده می‌دهد و سندی نمی‌سازد. منبع جدید لینک `Leave Type` (بدون مرخصی اختیاری) به فرم‌ساز افزوده شد و ساعت‌های «روز بعد» اکنون با کلید همراه `<execution_key>__next_day` به اجراکننده می‌رسند (پیش‌تر حذف می‌شدند). کلید افزودنی `before_or_equal` (+ `before_or_equal_message`) برای فیلد تاریخ، مثلاً «نیم‌روز داخل بازه» (در ارسال و در اپ یکسان)، و `time_after` (+ `time_after_message`) برای فیلد ساعت با احتساب «روز بعد»؛ مقایسهٔ تاریخ‌های `after_or_equal` با مقدار خالی دیگر خطا نمی‌دهد. بدون نیاز به مهاجرت یا تنظیم جدید.

- محرمانگی فیلدهای فرم: علامت `sensitive` فرم‌ساز اکنون به فیلد گردش‌کار نگاشت‌شده منتقل می‌شود (جزئیات درخواست، فهرست جست‌وجو و تغییرات ارسال مجدد). متن اعلان و توضیح فعالیت در اقدام «ارسال اعلان» و سند ساخته‌شده با «ایجاد سند» مقدار محرمانه را نشان نمی‌دهد (`محرمانه`). در اجرای پس از تأیید، پارامتر متنی که از فیلد محرمانه می‌آید به‌جای متن واقعی با جملهٔ «محرمانه؛ جزئیات در درخواست … است.» در سند بومی و Comment ثبت می‌شود. بدون نیاز به مهاجرت یا تنظیم جدید.

- گواهی اشتغال به کار (`certificate_issue`): پس از تأیید نهایی، گواهی با شمارهٔ ترتیبی `CERT-سال-#####` و سربرگ شرکت (Letter Head پیش‌فرض Company) به‌صورت PDF خصوصی به درخواست پیوست می‌شود. اطلاعات فقط از Employee، Company و در صورت درخواست فرم از آخرین Salary Structure Assignment ثبت‌شده (submit) گرفته می‌شود؛ کارمند غیرفعال یا خارج‌شده، نبود رکورد حقوق، زبان انگلیسی و نبود سربرگ به نتیجهٔ «نیازمند بررسی» با دلیل فارسی ختم می‌شود و شماره‌ای مصرف نمی‌شود. اجرای مجدد گواهی دوم نمی‌سازد. دریافت با `workflow_request.get_certificate` فقط برای درخواست‌دهنده، HR Manager و System Manager همان شرکت است (مجوز File و `get_attachment` هم همین قاعده را دارند)؛ `get_request` کلید `certificate` دارد. بدون مهاجرت؛ WeasyPrint باید روی سرور بارگذاری شود و شرکت به Letter Head پیش‌فرض نیاز دارد.
- تأیید دریافت تجهیز (N6): پس از ثبت پیش‌نویس تحویل تجهیز (`asset_movement`، جهت تحویل)، برای درخواست‌دهنده وظیفهٔ «تأیید دریافت تجهیز» در کارتابل ساخته می‌شود. نقطهٔ توسعهٔ عمومی `NativeResult.followup` در همان savepoint سند اجرا می‌شود. `request_followup.confirm_receipt` حرکت دارایی را ثبت نهایی می‌کند (ERPNext متصدی را تعیین می‌کند) و `request_followup.reject_receipt` با «علت عدم دریافت» پیش‌نویس را نگه می‌دارد و به مدیران منابع انسانی و انبار شرکت اعلان می‌دهد. فقط خود درخواست‌دهنده؛ تأیید دوباره، لغو حرکت دارایی و وظیفهٔ بسته با پیام فارسی رد می‌شوند و لغو یا حذف حرکت، وظیفهٔ باز را لغو می‌کند. `complete_workflow_task` و ذخیرهٔ پیش‌نویس این وظیفه را رد می‌کنند. جزئیات: `docs/api/form-execution.md`. بدون DocType یا فیلد جدید؛ نیازی به `bench migrate` نیست، فقط راه‌اندازی مجدد برای خواندن `doc_events` تازه در `hooks.py`.

- اجرای ثبت‌نام آموزشی (`training_enrollment`): پس از تأیید، درخواست‌دهنده به فهرست شرکت‌کنندگان دوره‌ای که هنوز پیش‌نویس است افزوده می‌شود؛ دورهٔ ثبت‌شده هرگز تغییر نمی‌کند و نتیجه «نیازمند بررسی» با اعلان به منابع انسانی است. ثبت‌نام تکراری، دورهٔ لغوشده/برگزارشده و دورهٔ شرکت دیگر با پیام فارسی رد می‌شود و ردیف دوره هنگام اجرا قفل می‌شود. بدون نیاز به مهاجرت یا تنظیم جدید.

- اجرای تسویه حساب (`exit`): پس از تأیید، پیش‌نویس Exit Interview و Full and Final Statement و تاریخ پایان همکاری کارمند به‌صورت اتمی ثبت می‌شود؛ ثبت تسویه دوم برای همان کارمند هنگام ارسال و اجرا رد می‌شود (هوک اختیاری `validate_submit` در رجیستری). بدون نیاز به مهاجرت یا تنظیم جدید.

- اجرای تغییر شیفت: ساخت اتمی پیش‌نویس‌های بومی تغییر و جابه‌جایی شیفت با اعتبارسنجی HRMS؛ بدون نیاز به مهاجرت یا تنظیم جدید.
- Approved form results requiring HR action now persist terminal `Needs Review`, show «نیازمند بررسی» with the reason restricted to privileged viewers, and notify the requester and HR/System Managers once. Asset direction Select ids `issue`/`receipt` map to native purposes. Run `bench migrate` to add the status option and normalize previously stored `needs_review` values; no new site configuration.
- Fix employee advance execution to resolve the requester from the workflow request owner, retaining active employee and company checks. No migration or site configuration is required.
- Create draft HRMS employee advances from approved form parameters with company currency, validated receivable account and Persian prerequisite errors. No migration or site configuration is required.


- A request returned for correction can be edited once by its owner: `get_request` returns `return_reason`, `can_edit` is true while it is returned, and `update_request` records a `Resubmitted` activity with the changed fields and restarts the review from the first stage after the form. No migration is required.

- Workflow decisions now always require a Persian reason for rejection or return, block self-approval, and mask form fields marked `sensitive` outside the owner, workflow participants, and System/HR managers. No migration is required.

Deployment: run `bench --site <site> migrate` (adds a search index on `ASOUD Workflow Activity.workflow_instance`; new `reminder_at` field on `ASOUD Internal Communication`; new `In Progress` option on the recipient `directive_state`).
Deployment: run `bench --site <site> migrate` (adds Form Entry reference indexes for approval execution; adds a search index on `ASOUD Workflow Activity.workflow_instance`; new `reminder_at` field on `ASOUD Internal Communication`; new `In Progress` option on the recipient `directive_state`).

Fixed:

- Paged workflow task/instance lists filter directive access in SQL (no per-row `get_doc`), keep `meta.total`, and compute the cursor after filtering.
- `dispatch_reminders` isolates each task; `reminder_at` with an offset or `Z` is converted to the site timezone. Reminders need the scheduler enabled (see `docs/directives-implementation.md`).

Added:

- `get_request` returns `execution` (state, Persian label, privileged-only error, reference) kept apart from `status_key`, computed in `services/request_execution.py`; workflow activity rows carry optional `before`/`after`. Needs `bench migrate` (new `ASOUD Workflow Activity.change_json`). See `docs/api/request_templates.md`.
- Employee schedule form capability: `forms.employee_schedule` reads HRMS Shift Assignment,
  Employee default shift and Holiday List for a bounded 62-day range; schema version 2 gains
  the additive read-only `Schedule` field, and shift-change tables are revalidated on submit.
  No migration is required.
  A colleague's schedule is readable only through a form with an `exclude_self` Employee link
  (`form`/`field` arguments) or by HR / System managers; others get a Persian permission error.
- Approval execution for versioned request forms: executor catalog, form and stage parameter validation, completed-step overrides, and native draft dispatch after final approval with isolated rollback and retry. Reuses the existing native result fields. Executor registration is separate; no example executor is installed in production. Run migrate for the Form Entry reference indexes; no native fields are added.

- Attendance correction form executor: missing entry/exit creates one native Employee Checkin; existing-time corrections and other cases return `needs_review` with a Persian explanation. Existing Checkins are preserved. A stored requester Employee must match the request owner, company and active status; an invalid selection is never replaced with another Employee. No migration; requires the form execution framework to dispatch approved forms. HR review notifications await a shared helper.
- Approved form requests can create draft equipment Issue/Receipt movements with requester custody checks. No migration. See `docs/api/form-execution.md`.

- Request-bound workflow step validation for approved amounts and per-row quantities, enforced during task completion. No migration. See `docs/api/forms.md`.
- `get_request` returns `viewer` (is the caller the requester, and their own open task with the stage's decision flags) for an in-page decision card.
- `get_request` returns `stages` (real workflow steps with status, assignees and times) and instance activity rows carry `actor_name` (`services/request_timeline.py`, `integration_tests/test_request_stages.py`).
- Form schema support for read-only time comparison boxes, next-day Time companions for
  overnight attendance, current native Contract start defaults (with joining-date fallback),
  and real HRMS Training Event course, trainer, location and attendee-count attributes. No migration.
- Form builder record sources: Link sources `Attendance`, `Shift Type`, `Training Event`, `Asset` scoped to the signed-in Employee on both `get_link_options` and submission (`meta.reason = 'no_employee'`), row `extra` attributes, `exclude_self`, `fetch_from` (recomputed server side), `not_equal`, unique table columns, and `default_source` `employee_number` / `default_shift`. No migration. See `docs/api/forms.md`.
- Form schema support for Select display styles, section presentation/collapse metadata,
  field help text, Date `after_or_equal` validation, and Employee designation and joining-date defaults.
- Submission enforcement for visible required repeatable tables and their minimum row count.
- Directive `start` action: the assigned recipient moves from Pending to In Progress without completing the execution task. Only the recipient can start, and only once.
- Directive progress reports: `report` accepts `report_type` (`final`, the default, or `progress`). A progress report is stored as a completed Workflow Task, keeps the execution task open, notifies the issuer and never requests approval.
- Directive reminders: the issuer can set `reminder_at` on a draft. At issue time it must be in the future and before the due date. A minute scheduler job (`dispatch_reminders`) notifies the assignee once per open report task.
- Paginated directive `reports` and `history` (50 rows per page, `next_cursor`), with access scoping applied in the database before pagination. `reports` accepts an `author` filter: the issuer may filter by any executor, an executor only by self.
- Workflow task and instance list endpoints accept `start` and `paged=1` and return `{items, next_cursor}`. The default list response is unchanged.
- Integration tests for start, progress reports, report type validation, reminders, and pagination (`integration_tests/test_directives.py`), plus a pure test for the directive status summary (`tests/test_directive_state.py`).

Changed:

- A directive whose executors are all Pending reads as `Issued`; it previously read as `In Progress`.

Changed:

- One Employee may occupy at most one position across the whole organization chart, including v2 `occupants` rows. Chart saves and import previews/applies that would place the same Employee in two positions are refused with a Persian message naming the Employee. Charts that already contain such duplicates must be corrected before they can be saved again.

Fixed:

- Plain Department saves no longer take a company-wide lock. Deleting, disabling, moving a unit with positions, or deleting a unit that positions reference still locks the company and is refused.
- Renaming a unit's title is refused while legacy chart positions (no `department_id`) reference it by title, so those positions are not orphaned. Link them to the unit in the chart first.

Tests and documentation:

- Pure tests for the Department guard and cross-position occupant rule; integration tests for the cross-position refusal and title rename behaviour; `test_organization` added to the integration module loop.
- API reference for organization units and import in `docs/api/organization.md`.

Performance and contract:

- `directives.reports` reads the review tasks of a page in one query instead of one lookup per report. Response shape and statuses are unchanged; when a report has more than one review row, the earliest one is used.
- `directives.history` applies access scope and the page limit inside each UNION branch, and orders each branch by the indexed `created_on`, so the query reads at most one page per branch.
- `list_my_workflow_tasks` and `list_my_workflow_instances` with `paged=1` document that a page can be short or empty while `next_cursor` is set. The cursor is computed from the raw database page, so clients keep paging until `next_cursor` is null (see `docs/workflow-runtime-v1.md`).

## 0.16.0 - 2026-10-18

Deployment: run `bench --site <site> migrate` (new DocTypes: `ASOUD Form`, `ASOUD Form Revision`, `ASOUD Form Entry`, `ASOUD Calendar Scope`, `ASOUD Calendar Holiday`; directive receipts). Pairs with app 0.28.0.

Added:

- Advanced formula functions `IF` (with lazy branch evaluation), `ROUND`, `MAX`, and `MIN` across scalar values and repeatable table columns.
- Comparison operators (`>`, `<`, `=`, `==`, `>=`, `<=`, `!=`) for conditional formula evaluation.
- Arithmetic operator precedence (`*`, `/`, `%` before `+`, `-`), negative numbers, parentheses `()`, and nested expressions in formula calculation.
- Extended shared formula vectors fixture to 55 test cases with parity verification against Flutter engine.
- Multi-step `chain` formula operator in form schema validation and Decimal evaluation matching Flutter engine parity, with left-to-right calculation, precision rounding, divide-by-zero protection, and dependency cycle validation.
- Shared formula evaluation vectors test suite ensuring backend/Flutter engine parity across operations, precision, rounding, and Persian numerals.
- Versioned form schema validation supporting `schema_version` 1 and 2, enforcing version 2 on `save_form`, and rejecting unsupported versions.
- Pure `migrate_schema` and `migrate_record` functions upgrading legacy v1 schemas to v2 with deterministic option IDs and value/rule mapping on read across `get_form`, `list_forms`, and `get_entry` while preserving immutable database revisions.
- Fixture test pair `form_schema_legacy_v1.json` and `form_schema_legacy_v2.json` for cross-engine migration parity.
- Versioned form-builder API coverage and documentation, including stable schema IDs,
  immutable published revisions, entry revision checks, and company-scoped calendar coverage.
- Integration tests for directives lifecycle (`test_directives.py`: draft, issue, transfer,
  report submission, change request, review approval, close, and cross-company tenant isolation).
- Dedicated integration tests for calendar scope and organization holidays (`test_calendar.py`).

Fixed:

- Restore active employee consumption on form-builder and calendar personal endpoints (plain
  employees can list published forms, submit request forms, read own entries, and manage personal
  reminders; designer endpoints and holiday management remain manager-gated, and document forms
  rely on native ERPNext DocType permissions).
- Persist new `ASOUD Form`, `ASOUD Calendar Scope`, and `ASOUD Calendar Holiday` records via `insert`
  to support deterministic identifiers before insert.

## 0.15.3 - 2026-10-11

Deployment: the release contains a patch (`v0_15_3.normalize_persian_digits`): run `bench --site <site> migrate`. No new DocTypes.

Security:

- `party.save_party` calls `require_company` on the loaded profile's own company, so a role scoped to another company can no longer move a foreign party into its own tenant and read its PII (F-P1).
- `account.delete_account`/`update_account` resolve the floating detail's linked record and `require_company` it, so a detail of another company can no longer be deleted, renamed or disabled through a shared detail group (F-P2).
- `floating_detail.disable_floating_detail` requires the loaded detail's linked company before disabling (F-P3).
- `account.list_accounts` filters expanded floating details by the linked record's tenant, matching `floating_detail.list_floating_details` (F-P4).
- `projects.update_task_status` requires the task's project company when the caller is not the assignee, so a manager can no longer move tasks of a foreign company (F-P5).

Fixed:

- Persian (۰-۹) and Arabic-Indic (٠-٩) digits are normalised to ASCII at the write boundaries of `party.save_party`, `setup.save_office` and `personnel.update_personnel` (plus the Employee mirrors), so identifier and number columns (national/economic/registration/postal codes, phone/mobile/fax, account/card/IBAN numbers, fiscal year and code digit counts) never store non-ASCII digits.
- Migration patch `v0_15_3.normalize_persian_digits` converts existing values in those columns of `ASOUD Party Profile`, `ASOUD Company Setup`, `ASOUD Personnel Record` and `Employee`; it only rewrites rows that contain a Persian/Arabic-Indic digit and is safe to re-run.

## 0.15.2 - 2026-10-10

Security:

- `party.save_party` redacts `bank_name`, `iban`, `account_number`, `card_number` and `account_holder` from its response for roles without bank access (and ignores such `bank_*` inputs), matching `party.list_parties` (F5).
- `hr.organization_tree` calls `require_company(company)` before reading the department tree, closing a cross-company read (F7).
- `floating_detail.list_floating_details` returns only details whose linked record belongs to a company the caller may access; rows with no linked record stay visible to `System Manager`/`Accounts Manager` only (F8).

## 0.15.1 - 2026-10-10

Fixed:

- Seed `ASOUD Company Setup` row for demo company with office_saved, accounting_saved, roles_saved all 1 and enabled_roles_json `["System Manager"]` so setup status resolves as complete.
- Return management-only dashboard payload with `manager_access: true` for System Manager and HR Manager users without a linked Employee in `hr.get_dashboard`.
- Accept str, JSON list string and list for `item_code` normalization in `stock_balance` report filters and API.
- Document and pin with regression tests the current behaviour of `request_query` (list) vs `request_permission` (read) for privileged roles in `docs/access-control-v1.md`.

## 0.15.0 - 2026-10-09

Deployment: run `bench migrate` (new DocTypes ASOUD Action Execution, ASOUD Access Assignment). Workflows with System Action stages need `asoud_workflow_service_user` and `asoud_workflow_service_companies` in the site config.

Added:

- HR Manager read access to manager screens (writes and financial reports stay closed).
- Playwright e2e suites for HR access, automatic actions and sync request keys.
- Guarded automatic workflow actions and execution audit (`docs/automatic-actions-v2.md`).
- Preserved validated supplementary approval form fields.
- Workflow task outputs and terminal outcomes (`services/user_task_output.py`).
- Native role and personal access assignments (`api/v1/user_access.py`).

Fixed:

- Allowed `HR Manager` to access read-only manager endpoints required to open the office and settings dashboards (`setup.get_setup_status`, `role_management.catalog`, `role_management.permission_preview`, `workflow.list_workflows`, `workflow.get_workflow_design`, `workflow.workflow_form_options`, `workflow.workflow_condition_fields`) while preserving company isolation and preventing privilege escalation on definitions and writes (`docs/access-control-v1.md`).

## 0.14.0

Added:

- Request engine for the purchase, supply and leave templates (`docs/api/request_templates.md`).
  - `ASOUD Workflow Request` gains `template_key`, `template_version`, `requester_employee`,
    `status_key`, `search_text` and the `native_*` fields; `ASOUD Workflow Definition` gains
    `template_key`, `template_version` and `is_system_template`. Custom Fields:
    `Company.asoud_daily_working_hours`, `Company.asoud_request_cost_center_required`,
    `Leave Type.asoud_leave_category` and `asoud_request` on Material Request and Leave Application.
  - Template registry (`services/request_templates`), idempotent seeding per company on migrate
    and on company creation, and a locked form stage for system templates.
  - Request numbers `PR|SP|LV-<Jalali year>-####`; custom types keep `REQ-#####` without a gap.
  - New form field types `Time`, `System Select` and `Auto`, `visible_when`, `option_labels`,
    item-row notes and files, and the lookup sources behind `request_field_options`.
  - Stored `status_key` mirrored from the workflow instance, and a query-based
    `list_my_requests` with status tabs, `meta.counts`, search, filters and pagination.
  - Richer `get_request` (status, `can_edit`, `can_cancel`, attachments with scope, row files,
    comment count, native document), `list_request_comments`, `add_request_comment`,
    `get_attachment(thumbnail=1)`, and `create_native_document` to retry a failed native document.
  - `create_request` accepts `template_key`; uploads take a `ref` so duplicate file names work;
    `update_request` adds and removes files; `.xls` and `.doc` are allowed.
  - Error codes travel in `_server_messages[].title` (for example `REQUESTER_MISMATCH`).
  - Patches `v0_14`: backfill `status_key`/`search_text`, map Leave Type categories.
- Leave requests (`docs/api/leave_request.md`): `leave_request.get_leave_balance` and
  `leave_request.preview_leave_request` (read-only, business errors come back as data), daily and hourly
  leave with exact half-up hour/day maths, overlap, balance and HRMS dry-run rules, and error code
  `LEAVE_RULE_VIOLATION` for HRMS validations without a contract code.
  After final approval a daily request becomes an approved Leave Application and an hourly request a
  Leave Ledger Entry; purchase and supply requests become Material Requests. A failure is stored as
  `native_status = Failed` and can be retried with `create_native_document`.
- The demo seed creates the three system templates and six requests with template keys; reset keeps the
  shared native Workflow while a definition links it (`docs/demo-seed.md`).

Changed:

- `workflow_request.list_my_requests` no longer returns `values` and `attachments` per row
  (use `get_request`) and returns at most 100 rows per page.
- `workflow_request.create_request` takes `request_id` as before but its other arguments are
  keyword-friendly (`workflow_definition` or `template_key`); invalid JSON arguments now raise
  a validation error instead of a server error.

## 0.13.1

Security:

- `party.list_parties` now restores the accounting role gate before company-scope checks, so an Employee-only user cannot list party profiles for their own company.

Fixed:

- Demo seed fiscal-year handling now reuses a global Fiscal Year without adding a company row, avoiding accidental restriction of a shared year. Demo reset only deletes a seed-shaped Fiscal Year owned solely by the demo company and otherwise removes just the demo company row.

## 0.13.0

Fixed:

- `sync.execute_mutation` now binds an idempotency key to both the target method
  and payload fingerprint. Retrying the same write still returns the stored
  envelope, but reusing that key for different work returns
  `REQUEST_KEY_CONFLICT` instead of a successful response from the first write.
- `financial_reports.run_financial_report(..., report="stock_balance")` accepts a
  single `item_code` string and passes it to ERPNext's Stock Balance report in
  the list form the report expects.
- Workflow request list permission now matches direct-read permission for
  System Manager and HR Manager users within companies they can access, including
  request-related instances, tasks and activities.

Security:

- Replaced `frappe.only_for` with `erp_documents.require_roles` across all `api/v1`
  modules (`account`, `detail_group`, `floating_detail`, `party`, `purchase_request`,
  `role_management`, `setup`, `voucher`, `workflow`, `workflow_runtime`).
  `frappe.only_for` was bypassed in test mode (`in_test=True`), leaving role gates
  unprotected against regressions; `require_roles` enforces role requirements under tests.
- `projects.create_timesheet` now validates foreign and unknown projects on time
  logs without a task. Such logs now require a project belonging to the caller's
  company and read permission, preventing employees from logging time to projects
  of other companies.
- Every `voucher.*` endpoint (`list_vouchers`, `save_voucher`, `submit_for_approval`,
  `approve_voucher`, `reject_voucher`) now checks company access with
  `request_access.require_company`. `list_vouchers` and `save_voucher` require
  access to the specified company, and voucher state transitions verify access to
  the company owning the voucher.
- `party.save_party` and `party.disable_party` now check the company of the profile
  they act on. `save_party` also keeps the profile's company when the argument is
  omitted instead of clearing it, which could move a party out of its tenant.
- `detail_group.list_account_mappings` and `detail_group.save_account_mapping` now
  check `company` with `request_access.require_company`. `ASOUD Account Mapping`
  carries a company, and the read was built with `frappe.get_all`, so it returned
  another company's account-to-detail-group mapping. The detail group catalogue
  itself (`ASOUD Detail Group`) has no company and stays site-wide.
- `floating_detail.create_floating_detail` and `floating_detail.link_floating_detail`
  now check the company of the record a detail is attached to. `ASOUD Floating
  Detail` has no company column, so a Company User Permission never applied to it:
  an Accounts User of Company A could attach a detail to a Company B party, and
  that write altered the other company's party.
- Every `account.*` endpoint now checks `company` with
  `request_access.require_company`. The module gated on roles only and read with
  `frappe.get_all`, so a Company User Permission did not limit the chart of
  accounts at all.
- `purchase_request.purchase_request_options`, `create_purchase_request` and
  `list_my_purchase_requests` now check `company` with
  `request_access.require_company`. The option lists are built with
  `frappe.get_all`, which skips User Permissions, so an Accounts Manager restricted
  to one company received another company's warehouse list.
- `party.save_party` now refuses a profile with the `Employee` role unless the
  caller is `System Manager` or `HR Manager`. An accountant could otherwise
  rewrite Employee master data (gender, birth date, date of joining, designation)
  with permission checks disabled, and set the employee's bank details, bypassing
  the `PERSONAL_FIELDS` allow-list of `personnel.update_personnel`. The Employee
  write now goes through Frappe's own permission check, and only allow-listed
  fields are mirrored onto it.
- `party.list_parties` requires `company` and checks it with
  `request_access.require_company`. Without it the endpoint answered for every
  company and returned the bank name, IBAN and account numbers of parties the
  caller could not see. Bank fields are now returned only to `System Manager` and
  `Accounts Manager`, the roles that own the party master; an `Accounts User` gets
  the profile without them. See `docs/api/party.md`.
- `report.trial_balance` and `report.general_ledger` are now company scoped
  (`request_access.require_company`) instead of only role scoped, so a User
  Permission on `Company` really limits the ledger. `report.general_ledger` also
  works again on ERPNext v15 (it called `frappe.get_descendants_of`, removed in
  v15, and raised `AttributeError` for every request). See `docs/api/report.md`.

- Demo seed command for real test sites: `bench --site <site> execute
  asoud_erp.demo.seed.run` (and `reset=True` to remove exactly the marked
  records). Creates «شرکت نمونه آسود» (IRR, Iran) with fiscal year,
  departments, designations, 12 employees with a reporting chain, 4 users,
  leave/payroll/attendance, customers/suppliers/items with stock,
  submitted sales/purchase invoices, and workflow request types with
  requests in several statuses — all through standard ERPNext/HRMS
  documents and the asoud APIs. Refuses without developer_mode (or off
  test/demo sites) unless forced.   Demo parties carry the company currency
  and IRR price lists so every invoice is created without conversion;
  `asoud_erp.demo.seed.check` reports remaining demo-marked records.
  `selling.create_sales_invoice` and `buying.create_purchase_order` accept
  optional `currency` and price-list overrides (a new document otherwise
  inherits both from the default price list).
  See `docs/demo-seed.md`.

## 0.12.0

- Account operations of the personnel file (`auth`): enable/disable a login with
  `set_account_enabled` (idempotent per request id, and it clears the open
  sessions of a disabled account), `get_account_status` with roles, allowed
  modules and data scope, and `get_login_history` from the native Activity Log
  and sessions without exposing session ids.
- «ارسال مجدد دعوت» is refused once the account has a recorded login, with a
  Persian message pointing at the password reset instead.
- `get_employee_access` also returns `access_level`, `modules` and `data_scope`,
  and `sync_employee_access` keeps the Company and Department User Permissions of
  the login in step with the Employee.
- The direct manager's photo is part of the organization section of the personnel
  file (the private Employee file first, the personnel photo record as fallback).
- Document templates (`document_templates`): map request, user, company and system values onto an
  ERPNext Journal Entry or Material Request; ready-made presets; account and warehouse checks.
- Workflow System Action stages now run: create a document from a template, change the request's
  display status, or send an in-app notification. Failures roll back and follow the Error route
  (or stop the instance as Failed and notify System Managers).
- `workflow.save_stage_routes` sets a stage's exits per decision (approve, reject, return,
  success, error).
- Submitting a generic request completes the requester's own form stage, so it reaches the next
  stage at once; the requester can edit it until it is reviewed (`update_request`) or cancel it
  (`cancel_request`).
- New assignees: the initiator's department and direct manager. Stage settings: description,
  rejection reason required, and for user tasks drafts on/off and all fields required.

Fixes:

- A rejection without its own route no longer continues along the stage's default route.
- A stage assignee who is not the requester (for example the direct manager) can open the generic
  request they act on; before, completing such a task failed with a permission error.

## 0.11.0

- Personnel file API (`personnel_file`): one aggregated file per employee from Employee, ERPNext
  Contract, HRMS promotions, transfers, salary assignments and slips, attendance, leave, private
  files and change history; the employee's own file and home screen; public announcements.
- HR writes: contracts with signed copies, promotions applied by HRMS, announcements.
- Personnel documents keep category, number and expiry; Employee fields for marital status, blood
  group, emergency contact, company email, branch, direct manager, probation and contract dates are
  editable through `personnel.update_personnel`. Bank details stay out of this API.

## 0.10.0

API modules on ERPNext/HRMS, each documented in `docs/api/` and covered by
integration tests on a real site (see `docs/backend-roadmap.md`):

- Dashboard: home figures (today's receipts and sales, bank and cash balances, open
  documents) and system status for the settings screen.
- Selling, sales pipeline and payments: sales invoices and returns, quotations,
  sales orders, delivery notes, payment entries with allocation.
- Stock and buying: items, stock balances, stock entries, purchase orders,
  receipts and supplier invoices.
- HR self-service: leave (balance, apply, approve), check-in, missions, salary
  advances, expense claims, payslips, attendance and holidays.
- Payroll (structure assignments, payroll runs), projects and timesheets, POS
  sessions and invoices, ERPNext financial and stock reports, IT issues and assets.
- Request types: short title, category and visibility settings; Multi Choice, User,
  Department and Item Table form fields validated against ERPNext masters; default
  values and help text on fields.

Security:

- Request creation enforces the request type's initiator roles and user-submission
  setting (both were stored but not checked).
- `sync.execute_mutation` binds a request key to its user; another user's key no
  longer replays that user's response.
