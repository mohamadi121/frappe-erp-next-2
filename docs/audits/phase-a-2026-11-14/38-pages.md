# ۳۸ — صفحات مدیریت گردش‌کار و Canvas

تاریخ: ۱۴۰۵/۰۸/۲۳ = 2026-11-14؛ مبنای ممیزی: اپ `c324e9e`، بک‌اند `448855f`. این سند تلفیق شواهد پذیرفته‌شدهٔ A1 تا A6 با تقدم REVIEW-NOTES.md است. بررسی کد یا اجرای مجدد تست در A7 انجام نشده است. ارجاع فایل و خط، مربوط به مبنای ممیزی است.

## حدود نتیجه‌گیری صفحات

«عملیاتی» در جداول منقول به معنی اتصال مشاهده‌شده در سورس و تست‌های گزارش‌شدهٔ کارگر است؛ بازگشایی در مرورگر/موبایل واقعی، حفظ داده پس از ورود مجدد و همهٔ نقش‌ها در سایت زنده در A7 آزموده نشده‌اند. ظاهر هندسی از سورس تأیید می‌شود؛ نبود هم‌پوشانی دستی یا صحت همهٔ عرض‌ها تأیید نشده است.

حذف اپ از frappe.client.delete می‌گذرد؛ delete_workflow مصرف نمی‌شود (A1-003). وجود on_trash و کنترل وابستگی مانع نتیجه‌گیری «حذف بدون هیچ گاردی» است. کنترل‌های درج/حذف مسیر گارد دارند، ولی add_workflow_stage و اتصال مبدأ غیر Condition استثنا هستند (A1-005). update_request_type_info برخلاف داوری اولیهٔ A2 از doc.save معمولی استفاده می‌کند؛ عبور بین‌دفتر صرفاً احتمالی است (A2-006).


<!-- شواهد منقول از A2.md، خطوط 5 تا 145 -->
## ۱. حوزه پوشش و چک‌لیست کامل بندبه‌بند (بخش‌های ۶ تا ۱۱)

### بخش ۶: صفحه فهرست گردش‌کارها (`workflow_list_page.dart`)
- **۱۵ بند کنترلی و نمایشی:**
  1. نمایش فهرست (`_WorkflowListView`) — ✔ (پوشش در بخش ۲.۶، خطوط ۶۹ تا ۱۴۴ در `workflow_list_page.dart`)
  2. جست‌وجو (`_SearchAndFilter` / فیلد جستجو) — ✔ (پوشش در بخش ۲.۶، خطوط ۲۳۱ تا ۲۵۸ در `workflow_list_page.dart`)
  3. فیلترها (تب‌های وضعیت `_StatusTabs`) — ✔ (پوشش در بخش ۲.۶، خطوط ۲۹۵ تا ۳۵۶ در `workflow_list_page.dart`)
  4. ایجاد گردش کار (دکمه `FilledButton.icon` با کلید `workflow-create`) — ✔ (پوشش در بخش ۲.۶، خطوط ۱۵۱ تا ۱۶۱ در `workflow_list_page.dart`)
  5. مشاهده جزئیات (آیتم منو `details` و دیالوگ `WorkflowDetailsDialog`) — ✔ (پوشش در بخش ۲.۶، خط ۴۷۰ و ۵۳۲ تا ۵۴۵ در `workflow_list_page.dart`)
  6. ویرایش / طراحی مراحل (آیتم منو `design` و ناوبری به `WorkflowDesignerPage`) — ✔ (پوشش در بخش ۲.۶، خط ۴۷۳ و ۵۲۳ تا ۵۳۰ در `workflow_list_page.dart`)
  7. انتشار / تغییر وضعیت (آیتم منو `activate` و متد `setStatus`) — ✔ (پوشش در بخش ۲.۶، خطوط ۴۸۰ تا ۴۸۳ و ۳۷۱ تا ۴۱۸ در `workflow_list_page.dart`)
  8. فعال‌سازی (`WorkflowDefinitionStatus.active`) — ✔ (پوشش در بخش ۲.۶، خطوط ۴۰۱ تا ۴۰۳ در `workflow_list_page.dart` و `workflow.py:1144`)
  9. غیرفعال‌سازی (`WorkflowDefinitionStatus.inactive`) — ✔ (پوشش در بخش ۲.۶، خطوط ۴۰۱ تا ۴۰۳ در `workflow_list_page.dart` و `workflow.py:1144`)
  10. حذف (آیتم منو `delete` با دیالوگ تأیید) — ✔ (پوشش در بخش ۲.۶، خطوط ۴۸۴ تا ۴۸۷ و ۳۷۹ تا ۳۹۳ در `workflow_list_page.dart`)
  11. وضعیت گردش کار (نمایش بج `_StatusBadge`) — ✔ (پوشش در بخش ۲.۶، خطوط ۴۶۳ و ۵۶۱ تا ۵۹۶ در `workflow_list_page.dart`)
  12. تعداد مراحل (`steps_count` در زیرنویس کارت) — ✔ (پوشش در بخش ۲.۶، خطوط ۵۱۳ تا ۵۲۱ در `workflow_list_page.dart` و `workflow.py:116`)
  13. نوع موجودیت (`target_doctype` و نمایش عنوان مرتبط) — ✔ (پوشش در بخش ۲.۶، خطوط ۵۳۴ تا ۵۴۵ و `workflow_details_dialog.dart:88`)
  14. نسخه گردش کار (`version_no` در جزئیات) — ✔ (پوشش در بخش ۲.۶، `workflow_details_dialog.dart:125` و `workflow.py:116`)
  15. مجوزهای دسترسی (`_WorkflowCapabilityGate` و گارد نقش‌ها) — ✔ (پوشش در بخش ۲.۶، خطوط ۴۵ تا ۶۷ در `workflow_list_page.dart`)

- **۷ سؤال ارزیابی موردی اجزا (ظاهر، عملکرد کنترل، دیتابیس، API، ذخیره، حفظ بعد از بازگشایی، نمایش خطا):**
  - پاسخ کامل و مستند در جدول جامع کنترل‌های بخش ۲.۶ ارائه گردید — ✔

---

### بخش ۷: فرم ایجاد گردش کار (`workflow_form_page.dart`)
- **فیلدهای واقعی پیاده‌سازی‌شده در سورس کد (تطبیق واقعی فرانت‌اند و بک‌اند):**
  1. عنوان گردش کار (`workflow-title`) — ✔ (پوشش در جدول بخش ۲.۷، `workflow_form_page.dart:176`)
  2. توضیح کوتاه (`workflow-description`) — ✔ (پوشش در جدول بخش ۲.۷، `workflow_form_page.dart:190`)
  3. تنظیمات ظاهری: رنگ و آیکون (`_AppearanceSettings`) — ✔ (پوشش در جدول بخش ۲.۷، `workflow_form_page.dart:206` و `301`)
  4. روش ایجاد: دستی / الگو (`_CreationModeOptions`) — ✔ (پوشش در جدول بخش ۲.۷، `workflow_form_page.dart:210` و `283`)
  5. ماژول (`module_key`) — ✔ (پوشش در جدول بخش ۲.۷، عدم وجود کشوی مستقل در فرم و استخراج خودکار از سند در `workflow_start_section.dart:64`)
  6. نوع موجودیت (`target_doctype`) — ✔ (پوشش در جدول بخش ۲.۷، مقداردهی پیش‌فرض `ASOUD Workflow Request` بدون دراپ‌داون در UI در `workflow_form_cubit.dart:49`)
  7. نوع شروع (`trigger_type`: دستی / فرم) — ✔ (پوشش در جدول بخش ۲.۷، `workflow_start_section.dart:118`)
  8. نقش‌های مجاز شروع دستی (`roles`) — ✔ (پوشش در جدول بخش ۲.۷، `workflow_start_section.dart:73` و `199`)
  9. انتخاب منبع سند/درخواست (`submission_source`) — ✔ (پوشش در جدول بخش ۲.۷، `workflow_start_section.dart:45` و `168`)
  10. مسیر ارسال فرم (`source_route`) — ✔ (پوشش در جدول بخش ۲.۷، `workflow_start_section.dart:208`)
  11. تنظیمات تکمیلی شروع (`WorkflowStartAdditionalFields`) — ✔ (پوشش در جدول بخش ۲.۷، `workflow_start_section.dart:223`)

- **۱۰ سؤال ارزیابی موردی فیلدها (ضرورت، تکرار، پیش‌فرض، منبع، فعال بودن کشو، گزینه‌ها، ذخیره، ماندگاری، اعتبارسنجی کلاینت/سرور):**
  - پاسخ کامل در جدول مشخصات فیلدهای فرم ایجاد در بخش ۲.۷ ارائه گردید — ✔

---

### بخش ۸: صفحه طراحی گردش کار / Canvas (`workflow_designer_page.dart` و `workflow_graph_canvas.dart`)
- **۱۵ بند امکانات Canvas:**
  1. نمایش مراحل (`WorkflowGraphCanvas` / `_GraphNode`) — ✔ (بخش ۲.۸، `workflow_graph_canvas.dart:133-162`)
  2. افزودن مرحله (`addStage` / `_showStagePicker`) — ✔ (بخش ۲.۸، `workflow_designer_page.dart:102-112` و `200-205`)
  3. حذف مرحله (`remove_path` و حذف شاخه) — ✔ (بخش ۲.۸، `workflow_designer_page.dart:339-361`)
  4. اتصال مراحل (`_GraphPainter` و رسم منحنی‌های Bezier) — ✔ (بخش ۲.۸، `workflow_graph_canvas.dart:240-345`)
  5. حذف اتصال (گزینه `− حذف مسیر` روی آیکون زنجیر) — ✔ (بخش ۲.۸، `workflow_graph_canvas.dart:116` و `workflow_designer_page.dart:339`)
  6. جابه‌جایی مراحل (`onPanUpdate` و ذخیره مختصات با `savePositions`) — ✔ (بخش ۲.۸، `workflow_graph_canvas.dart:139-147` و `workflow_designer_cubit.dart:148`)
  7. انتخاب مرحله (`onTap` گره و نمایش کادر هایلایت) — ✔ (بخش ۲.۸، `workflow_graph_canvas.dart:149-160`)
  8. بازکردن تنظیمات مرحله (`_openStage` و ناوبری به صفحات تنظیمات اختصاصی) — ✔ (بخش ۲.۸، `workflow_designer_page.dart:145-198`)
  9. ذخیره نمودار (`savePositions` و فراخوانی API) — ✔ (بخش ۲.۸، `workflow_designer_cubit.dart:148-170`)
  10. بازیابی نمودار (`load` و فراخوانی `get_workflow_design`) — ✔ (بخش ۲.۸، `workflow_designer_cubit.dart:38-66`)
  11. نمایش مسیرهای شرطی (مسیرهای سبز/قرمز با برچسب بلی/خیر) — ✔ (بخش ۲.۸، `workflow_graph_canvas.dart:278-281` و `workflow_graph_geometry.dart:113-115`)
  12. نمایش مسیرهای تأیید و رد (انشعاب هندسی تأیید/رد/بازگشت) — ✔ (بخش ۲.۸، `workflow_graph_geometry.dart:91-103`)
  13. بزرگ‌نمایی و کوچک‌نمایی (`InteractiveViewer` با مقیاس ۰.۵۵ تا ۲.۲) — ✔ (بخش ۲.۸، `workflow_graph_canvas.dart:74-78`)
  14. عملکرد در موبایل و ریسپانسیو (محاسبه `fit` مقیاس در لایه‌بندی) — ✔ (بخش ۲.۸، `workflow_graph_canvas.dart:65-73`)
  15. جلوگیری از هم‌پوشانی مراحل (عدم وجود موتور Auto-layout و ریسک هم‌پوشانی دستی) — ✔ (بخش ۲.۸، خطوط ۵۳ و ۶۱-۶۴ در `workflow_graph_canvas.dart`)

---

### بخش ۹: اشکال هندسی مراحل (`WorkflowGraphGeometry` و `workflow_graph_canvas.dart`)
- بررسی مقایسه‌ای کامل ۷ مرحله (شکل، رنگ و کد هگز، عنوان فارسی و خطوط اتصال) با جدول مرجع مصوب — ✔ (مستند در جدول تفصیلی بخش ۲.۹)

---

### بخش ۱۰: مدیریت اتصال و حذف مرحله (`workflow_paths.py` و ویجت زنجیر)
- **۸ بند کنترل زنجیر و ویرایش مسیر:**
  1. وجود کنترل زنجیر با آیکون `link_rounded` روی ترانزیشن‌ها — ✔ (بخش ۲.۱۰، `workflow_graph_canvas.dart:109-130`)
  2. عملکرد منوی بازشونده شامل `+` و `−` — ✔ (بخش ۲.۱۰، `workflow_graph_canvas.dart:114-118`)
  3. افزودن مرحله بین‌راهی و حفظ اتصال اولیه (`insert_workflow_stage`) — ✔ (بخش ۲.۱۰، `workflow.py:533-573`)
  4. حذف مسیر بدون خرابی ساختار کلی نمودار (`removal_plan` و `remove_path`) — ✔ (بخش ۲.۱۰، `workflow_paths.py:24-40` و `workflow_paths.py:50-67`)
  5. مسدودسازی حذف و تغییر در صورت وجود اجرای فعال — ✔ (بخش ۲.۱۰، `workflow_paths.py:19-21`)
  6. دیالوگ تأیید قبل از اعمال حذف با نمایش لیست مراحل حذفی — ✔ (بخش ۲.۱۰، `workflow_designer_page.dart:347-353`)
  7. حفظ شناسه‌ها و صدور توکن لغو موقت (`discard_inserted_stage`) — ✔ (بخش ۲.۱۰، `workflow_paths.py:71-125`)
  8. ذخیره و بازیابی پس از درج/حذف مسیر — ✔ (بخش ۲.۱۰، `workflow_designer_page.dart:334` و `356`)

---

### بخش ۱۱: صحت ساختار نمودار (اعتبارسنجی سرور)
- **۱۲ بند اعتبارسنجی ساختار گراف:**
  1. مرحله شروع معتبر — ✔ (`activation_requirements` در `workflow_contract.py:71`)
  2. مرحله پایان معتبر — ✔ (`activation_requirements` در `workflow_contract.py:71`)
  3. مراحل بدون ورودی — ✔ (`activation_requirements` در `workflow_contract.py:90-104`)
  4. مراحل بدون خروجی — ✔ (`activation_requirements` در `workflow_contract.py:90-104`)
  5. اتصالات ناقص / ارجاع به خارج — ✔ (`activation_requirements` در `workflow_contract.py:75-77`)
  6. اتصالات تکراری به یک مقصد — ✔ (`connect_workflow_stages` در `workflow.py:476` و `503`)
  7. مسیرهای غیرقابل‌دسترس از شروع — ✔ (`activation_requirements` در `workflow_contract.py:90-96`)
  8. حلقه‌های نامعتبر (حلقه بدون خروج و خودارجاعی) — ✔ (`validate_workflow` در `workflow_check.py:119-126`)
  9. خروجی‌های بدون مقصد منتهی به پایان — ✔ (`activation_requirements` در `workflow_contract.py:97-104`)
  10. اتصال به مرحله حذف‌شده — ✔ (`workflow_check.py:15` و `workflow_paths.py:28`)
  11. مسیرهای شرطی ناقص (کمتر یا بیشتر از ۲ انشعاب True/False) — ✔ (`_validate_saved_routes` در `workflow_contract.py:41-44`)
  12. اتصال خروجی از مرحله پایان — ✔ (`connect_workflow_stages` در `workflow.py:499` و `workflow_contract.py:38-40`)

---

## ۲. گزارش‌های تحلیلی و فنی تفکیکی

### ۲.۶. صفحه فهرست گردش‌کارها (`WorkflowListPage`)

صفحه فهرست به عنوان دروازه ورود به مدیریت و نظارت بر گردش‌کارها پیاده‌سازی شده است. ساختار معماری آن بر پایه الگوی BLoC/Cubit با کلاس `WorkflowListCubit` و ریپازیتوری‌های `WorkflowRepository` (و پیاده‌سازی شبکه `FrappeWorkflowRepository`) و `WorkflowCardRepository` شکل گرفته است.

#### جدول جامع کنترل‌ها، هندلرها، فراخوانی‌های API و دیتابیس
| عنوان کنترل / بخش | محل دقیق در ویجت فرانت‌اند | متد هندلر فرانت‌اند | متد ریپازیتوری کلاینت | تابع API و متد بک‌اند | جدول و فیلدهای دیتابیس | گارد مجوز و دسترسی | وضعیت عملکرد واقعی و تست |
|---|---|---|---|---|---|---|---|
| **فهرست گردش‌کارها** | `workflow_list_page.dart:119` (`ListView`) | `WorkflowListCubit.load` (خط ۳۰) | `FrappeWorkflowRepository.getWorkflows` (خط ۴۲۲) | `asoud_erp.api.v1.workflow.list_workflows` (`workflow.py:83`) | جدول `tabASOUD Workflow Definition` | نقش‌های `System Manager`, `Accounts Manager`, `Accounts User`, `HR Manager` (`workflow.py:89`) | کاملاً عملیاتی؛ لود صفحه‌بندی‌شده تا ۲۰۰ آیتم، نمایش اسکلت لودینگ و کنترل خطا |
| **جست‌وجو** | `workflow_list_page.dart:248` (`TextField`) | `WorkflowListCubit.search` (خط ۵۹) با تاخیر ۳۵۰ms | `getWorkflows(search: ...)` | پارامتر `search` در `list_workflows` (`workflow.py:105-107`) | جستجوی SQL Like در `workflow_title` و `workflow_code` | همان گارد متد فهرست | کاملاً عملیاتی؛ با تایپ کاربر لیست زنده فیلتر می‌شود |
| **فیلتر وضعیت** | `workflow_list_page.dart:295` (`_StatusTabs`) | `WorkflowListCubit.setFilter` (خط ۶۵) | `getWorkflows(status: ...)` | پارامتر `status` در `list_workflows` (`workflow.py:90-100`) | فیلتر روی فیلد `status` مقادیر `Active`, `Inactive`, `Archived` | همان گارد متد فهرست | کاملاً عملیاتی؛ فیلتر دیتابیسی تب‌ها دقیق عمل می‌کند |
| **مرتب‌سازی** | `workflow_list_page.dart:240` (`OutlinedButton` آیکون tune) | `_showSortSheet` (خط ۲۶۰) و `setOrder` (خط ۷۰) | `getWorkflows(orderBy: ...)` | پارامتر `order_by` در `list_workflows` (`workflow.py:92-97`) | مرتب‌سازی `modified desc/asc`, `title asc`, `code asc` | همان گارد متد فهرست | کاملاً عملیاتی؛ شیت انتخاب باز شده و پس از انتخاب بازخوانی می‌شود |
| **دکمه ایجاد جدید** | `workflow_list_page.dart:151` (`FilledButton.icon`) | رویداد `onPressed` (خط ۱۵۳) | ناوبری به `WorkflowFormPage` و بازخوانی پس از بستن | تابع ساخت پیش‌نویس `create_workflow_draft` (`workflow.py:188`) | درج در `tabASOUD Workflow Definition` | `capabilities.canManageWorkflows` (خط ۱۴۷) | کاملاً عملیاتی؛ فقط برای مدیران دارای مجوز نمایش داده می‌شود |
| **مشاهده جزئیات** | `workflow_list_page.dart:429` (کلیک روی کارت) و ۴۷۰ (منوی پاپ‌آپ) | `_showDetails` (خط ۵۳۲) | `FrappeWorkflowRepository.getDesign` (خط ۴۸) | `asoud_erp.api.v1.workflow.get_workflow_design` (`workflow.py:283`) | جداول Definition, Stage, Transition | نقش‌های `System Manager`, `Accounts Manager`, `Accounts User`, `HR Manager` | کاملاً عملیاتی؛ دیالوگ جزئیات باز شده و وضعیت پیش‌نیازها را خلاصه می‌کند |
| **طراحی مراحل** | `workflow_list_page.dart:473` (گزینه منوی `design`) | `_openDesigner` (خط ۵۲۳) | ناوبری به `WorkflowDesignerPage` و بازخوانی فهرست | `get_workflow_design` و ذخیره چیدمان `update_stage_positions` | جداول Definition و Stage | `capabilities.canManageWorkflows` (خط ۴۷۳) | کاملاً عملیاتی؛ وارد محیط Canvas می‌شود و پس از بازگشت، تغییرات منعکس می‌گردد |
| **کپی مستقل سیستم** | `workflow_list_page.dart:477` (گزینه `copy-system`) | `_copySystem` (خط ۵۴۷) | `WorkflowTemplateRepository.copyFromWorkflow` (خط ۸۳) | `workflow_templates.create_from_template` (`workflow_templates.py:16`) | کپی رکورد Definition و ساخت مراحل جدید | `capabilities.canManageWorkflows` و قالب سیستمی بودن فرایند | کاملاً عملیاتی؛ دیالوگ عنوان را پرسیده و کپی مستقل با کد جدید می‌سازد |
| **شروع دستی فرایند** | `workflow_list_page.dart:471` (گزینه `start-manual`) | نمایش دیالوگ `WorkflowManualStartDialog` (خط ۴۹۰) | `WorkflowStartExecutionRepository.start` (خط ۱۶) | `asoud_erp.api.v1.workflow_runtime.start_workflow_instance` (`workflow_runtime.py:734`) | درج رکورد در `tabASOUD Workflow Instance` و `Activity` | نقش‌های مجاز آغازگر در تنظیمات شروع فرایند | کاملاً عملیاتی؛ عنوان و علت را پرسیده و نمونه اجرا ایجاد می‌کند |
| **تغییر وضعیت (فعال/غیرفعال)** | `workflow_list_page.dart:480` (گزینه `activate`) | `_operate('activate')` (خط ۳۷۱) | `WorkflowCardRepository.setStatus` (خط ۳۴) | `asoud_erp.api.v1.workflow.set_workflow_status` (`workflow.py:1144`) | فیلد `status` در جدول `tabASOUD Workflow Definition` | نقش‌های `System Manager`, `Accounts Manager` | کاملاً عملیاتی؛ وضعیت برعکس شده و با سرور هماهنگ می‌گردد |
| **حذف گردش‌کار** | `workflow_list_page.dart:484` (گزینه `delete`) | `_operate('delete')` (خط ۳۷۹) با نمایش `AlertDialog` تأیید | `WorkflowCardRepository.delete` (خط ۴۶) | `frappe.client.delete` و در بک‌اند `delete_workflow` (`workflow.py:1166`) | حذف مستندات در Definition, Stage, Transition | `canDelete` و عدم سیستمی بودن و دسترسی Delete | کاملاً عملیاتی؛ در صورت وجود سابقه، سرور مانع حذف می‌شود |

#### تحلیل عمیق رفتار سیستم در مواجهه با نمونه‌های اجرای فعال (Active Instances):
۱. **رفتار در عملیات حذف (Delete):**
   - در سطح فرانت‌اند، بررسی `item.canDelete` انجام می‌شود که از فیلد `can_delete` سرور ناشی می‌شود (`workflow.py:137`).
   - در سطح بک‌اند، تابع `delete_workflow` در `workflow.py:1166` متد محلی `frappe.delete_doc` را فراخوانی می‌کند که هوک `on_trash` داک‌تایپ `ASOUD Workflow Definition` (`asoud_workflow_definition.py:46`) را به کار می‌اندازد.
   - هوک `on_trash` تابع `delete_definition` در `workflow_lifecycle.py:55` را صدا می‌زند. این تابع با قفل دیتابیسی `for update` بررسی می‌کند:
     ```python
     for doctype in ('ASOUD Workflow Instance', 'ASOUD Workflow Request'):
         if frappe.db.sql(f'select name from `tab{doctype}` where workflow_definition=%s limit 1 for update', (doc.name,)):
             frappe.throw('این گردش‌کار دارای درخواست یا سابقهٔ اجرا است؛ حذف آن مجاز نیست. می‌توانید آن را غیرفعال کنید.')
     ```
     همچنین تسک‌ها و فعالیت‌های مرتبط در `ASOUD Workflow Task` و `ASOUD Workflow Activity` نیز بررسی می‌شوند. بنابراین حذف فیزیکی گردش‌کاری که حتی یک نمونه اجرا داشته باشد کاملاً غیرممکن و ایمن است.
۲. **رفتار در تغییر وضعیت و غیرفعال‌سازی (Deactivate):**
   - متد `set_workflow_status` در `workflow.py:1144` وضعیت فرایند را از `Active` به `Inactive` یا `Archived` تغییر می‌دهد.
   - **یافته معماری مهم:** بک‌اند هنگام تغییر وضعیت گردش‌کار به `Inactive`، وجود نمونه‌های در حال اجرای فعلی (`status = 'Running'`) را بررسی **نمی‌کند**. خوشبختانه موتور اجرای رانتایم هنگام ثبت یا تکمیل کارتابل (`complete_workflow_task` در `workflow_runtime.py:1376`) صرفاً بررسی می‌کند که وضعیت اینستنس در جریان `Running` باشد. با این حال، چنانچه گردش‌کار غیرفعال شود، آغازگر جدید نمی‌تواند نمونه اجرا کند (`workflow_runtime.py:768` و `794`)، ولی نمونه‌های در جریان همچنان می‌توانند به کار خود ادامه داده و کامل شوند. این رفتار مانع توقف ناگهانی فرایندهای جاری کارمندان است، اما از طرفی اجازه می‌دهد مراحل در حال اجرا بر اساس تعریفی پیش روند که ادمین آن را غیرفعال کرده است.
۳. **رفتار در ویرایش طراحی و مسیرها (Edit Design / Paths):**
   - طبق گارد `editable` در `workflow_paths.py:19-21`:
     ```python
     if doc.status == 'Active' or frappe.db.exists('ASOUD Workflow Instance', {'workflow_definition': definition}):
         frappe.throw('این گردش‌کار فعال است یا سابقهٔ اجرا دارد؛ برای تغییر مسیرها یک کپی مستقل بسازید.')
     ```
     اگر گردش‌کار فعال باشد یا حتی یک رکورد `ASOUD Workflow Instance` در کل دیتابیس برای آن وجود داشته باشد، متدهای درج مرحله، حذف مسیر و لغو ویرایش خطای اعتبارسنجی داده و هرگونه تغییر توپولوژی گراف را مسدود می‌کنند. همچنین در متد `save_start_settings` (`workflow_start_settings.py:80`) و متد `save_stage_settings` برای مراحل Wait و End (`workflow.py:840` و `workflow_condition_binding.py:43`)، وجود اینستنس در حال اجرا (`status = 'Running'`) ذخیره تنظیمات را متوقف می‌کند.


---

### ۲.۷. فرم ایجاد گردش کار (`WorkflowFormPage` و `WorkflowStartSection`)

فرم ایجاد گردش‌کار در فایل `workflow_form_page.dart` پیاده‌سازی شده و مدیریت حالت آن به عهده `WorkflowFormCubit` است. این فرم مسئول دریافت مشخصات اولیه فرایند و آغازگر آن است.

#### تحلیل تناقض فیلدهای فرم فرانت‌اند با نیازمندی‌های بک‌اند و ماژول‌ها:
- در بک‌اند، تابع `create_workflow_draft` در `workflow.py:188` الزاماً دو پارامتر `module_key` و `target_doctype` را به عنوان ورودی الزامی می‌پذیرد و در صورت نامعتبر بودن آنها خطای اعتبارسنجی صادر می‌کند (`workflow.py:227-232`).
- اما در فرانت‌اند، در فایل `workflow_form_page.dart` **هیچ Dropdown یا فیلد انتخابی برای `target_doctype` و `module_key` در بدنه اصلی فرم وجود ندارد!**
- نحوه کارکرد پنهان در سورس کد:
  ۱. فیلد `target_doctype` در مقداردهی اولیه `WorkflowFormCubit.load` (خط ۴۹) به صورت هاردکد برابر `'ASOUD Workflow Request'` قرار می‌گیرد.
  ۲. فیلد `module_key` به صورت پیش‌فرض از اولین ماژول موجود در پاسخ گزینه‌های سرور (`options.modules.firstOrNull?.key`) لود می‌شود (خط ۴۸).
  ۳. سپس در انتهای فرم، اگر کنترل `WorkflowStartSection` فعال باشد و کاربر دکمه «انتخاب درخواست یا سند» را لمس کند، شیت انتخاب سند `StageFormSourcePicker` باز می‌شود (`workflow_start_section.dart:59`). هنگامی که کاربری یک فرم درخواست یا سند را انتخاب می‌کند، کال‌بک `onModuleChanged` ماژول آن فرم را به کیوبیت پاس می‌دهد (`workflow_form_page.dart:237`).
  ۴. این عدم وجود انتخابگر مستقیم ماژول و داک‌تایپ، در مواردی که کاربر مایل به ایجاد یک فرایند عمومی مستقل از فرم‌های پیش‌ساخته است، باعث ابهام شدید و ارسال ماژول تصادفی (اولین ماژول) به سرور می‌گردد.

#### جدول مشخصات جامع فیلدهای فرم ایجاد گردش‌کار
| نام فیلد در کد | نوع کنترل در UI | منبع داده (Data Source) | مقدار پیش‌فرض | الزامی؟ | اعتبارسنجی فرانت‌اند | اعتبارسنجی سرور | وضعیت ذخیره و ماندگاری |
|---|---|---|---|---|---|---|---|
| **عنوان گردش‌کار** (`workflow_title`) | `TextFormField` با کلید `workflow-title` (`workflow_form_page.dart:177`) | ورودی کاربر | خالی (یا عنوان الگو در کپی) | بله | `workflow_form_cubit.dart:107` (طول بین ۳ تا ۱۴۰ نویسه با پیام فارسی) | `workflow.py:225` (`len(title) < 3`) با پیام انگلیسی | در فیلد `workflow_title` جدول `tabASOUD Workflow Definition` ذخیره و در بازگشایی لود می‌شود. |
| **توضیح فرایند** (`process_description`) | `TextFormField` چندخطی (`workflow_form_page.dart:191`) | ورودی کاربر | خالی | خیر | `workflow_form_cubit.dart:111` (حداکثر ۲۰۰۰ نویسه) | بدون محدودیت سخت‌گیرانه (ذخیره در Small Text) | در فیلد `process_description` جدول ذخیره و در بازگشایی لود می‌شود. |
| **رنگ شاخص** (`color_hex`) | انتخابگر دایره‌های رنگی در `_AppearanceSettings` (`workflow_form_page.dart:309`) | آرایه ثابت ۶ رنگ در کد | `#315CF5` (آبی اصلی) | بله | انتخاب از رنگ‌های ثابت یا حفظ مقدار قبلی | ذخیره در دیتابیس بدون اعتبارسنجی رگولاراکسپرشن | در فیلد `color_hex` جدول ذخیره می‌شود. |
| **آیکون فرایند** (`icon_key`) | انتخابگر مشبک آیکون‌ها در `_AppearanceSettings` (`workflow_form_page.dart:325`) | آرایه ثابت ۸ آیکون کاربردی | `'hub'` | بله | انتخاب از گزینه‌های موجود | ذخیره در دیتابیس | در فیلد `icon_key` جدول ذخیره می‌شود. |
| **روش ایجاد** (`creation_mode`) | دو گزینه انتخابی در `_CreationModeOptions` (`workflow_form_page.dart:289`) | دو مقدار ثابت `Custom` و `Template` | `'Custom'` | بله | اعتبارسنجی انتخاب | `workflow.py:237` (باید در `{"Custom", "Template"}` باشد) | در فیلد `creation_mode` دیتابیس ذخیره می‌گردد. |
| **ماژول گردش‌کار** (`module_key`) | فاقد دراپ‌داون در فرم اصلی؛ تغییر ضمنی با `onModuleChanged` | لیست ماژول‌های سرور `MODULE_DOCTYPES` | اولین ماژول سرور (معمولاً `Purchase`) | بله | `workflow_form_cubit.dart:115` (نباید خالی باشد) | `workflow.py:227` (بررسی وجود در `MODULE_DOCTYPES`) | در فیلد `module_key` ذخیره می‌شود. |
| **نوع داک‌تایپ هدف** (`target_doctype`) | **فاقد هرگونه کنترل یا دراپ‌داون در رابط کاربری!** | هاردکد داخلی کیوبیت | `'ASOUD Workflow Request'` | بله | `workflow_form_cubit.dart:115` (نباید خالی باشد) | `workflow.py:229` (تطابق با ماژول و نصب بودن داک‌تایپ در Frappe) | در فیلد `target_doctype` ذخیره می‌گردد. |
| **نحوه شروع فرایند** (`trigger_type`) | کارت دوتایی رادیویی (`workflow_start_section.dart:118`) | گزینه‌های `Document Event` (با فرم) یا `Manual` (دستی) | `Document Event` (فرمی) | بله | `workflow_form_cubit.dart:101-105` | `workflow_start_settings.py:validate_selection` | در کانفیگ جیسون مرحله شروع (`Start`) ذخیره می‌شود. |
| **نقش‌های شروع دستی** (`initiator_roles`) | باتم‌شیت چندانتخابی نقش‌ها (`workflow_start_section.dart:73`) | جدول `Role` از `workflow_form_options` | خالی | در حالت دستی بله | در حالت دستی نباید خالی باشد (`workflow_form_cubit.dart:102`) | بررسی معتبر بودن نقش‌ها در Frappe | در آرایه `initiator_roles` تنظیمات مرحله شروع ذخیره می‌شود. |
| **منبع فرم/درخواست** (`submission_source`) | باتم‌شیت جامع انتخاب فرم `StageFormSourcePicker` | جداول `tabASOUD Form` و نسخه‌های منتشرشده | خالی | در حالت فرمی بله | در حالت فرمی نباید خالی باشد (`workflow_form_cubit.dart:101`) | بررسی تطابق نسخه منتشرشده فرم با دفتر و فعال بودن فرم | در فیلد `source_form` و `source_revision` جدول Definition و تنظیمات مرحله شروع ذخیره می‌شود. |
| **مسیر ارسال فرم** (`source_route`) | فیلد انتخابی `AppSelectField` (`workflow_start_section.dart:209`) | مقادیر `Available`, `Default`, `Conditional` | `'Default'` | بله | مقادیر معتبر شیت | ذخیره در تنظیمات مرحله شروع | در کانفیگ مرحله شروع ذخیره می‌شود. |

---

### ۲.۸. صفحه طراحی گردش کار و عملکرد Canvas

محیط Canvas در `WorkflowDesignerPage` و ویجت اختصاصی `WorkflowGraphCanvas` پیاده‌سازی شده و قلب بصری سیستم مدیریت فرایند است.

#### تحلیل ۱۵ گانه قابلیت‌های Canvas:
1. **نمایش مراحل (`_GraphNode`):** در `workflow_graph_canvas.dart:133-162` پیاده‌سازی شده است. هر گره با استفاده از شکل هندسی اختصاصی خود رسم شده و عنوان مرحله، آیکون و مسیرهای خروجی را با لی‌آوت مناسب نمایش می‌دهد.
2. **افزودن مرحله جدید (`addStage`):** دکمه شناور پایین صفحه (`FilledButton.icon` در `workflow_designer_page.dart:103-112`) باتم‌شیت انتخاب مرحله (`_StagePickerSheet`) را باز می‌کند و پس از انتخاب نوع مرحله، متد `addStage` در کیوبیت فراخوانی می‌شود. این متد با صدا زدن API بک‌اند (`asoud_erp.api.v1.workflow.add_workflow_stage` در `workflow.py:347`) مرحله را بعد از آخرین مرحله خطی ثبت می‌کند.
3. **حذف مرحله و انشعابات:** از طریق آیکون زنجیر روی مسیرها و فراخوانی متد `remove_path` انجام می‌شود (`workflow_designer_page.dart:339`).
4. **رسم اتصالات و مسیرها (`_GraphPainter`):** در `workflow_graph_canvas.dart:240-345` توسط `CustomPainter` انجام می‌پذیرد. نقاط شروع و پایان خطوط به صورت دقیق روی مرز هندسی اشکال گره‌ها محاسبه می‌شوند (`WorkflowGraphGeometry.boundary`). خطوط با منحنی‌های درجه ۳ بزیه (`cubicTo`) و همراه با نوک پیکان جهت‌دار رسم می‌شوند.
5. **حذف اتصال:** روی هر یال ترانزیشن، آیکون زنجیر شامل گزینه منوی «− حذف مسیر» است که رویداد `onRemoveTransition` را فعال می‌کند.
6. **جابه‌جایی مراحل (Drag & Drop):** گره‌ها با `GestureDetector` و رویداد `onPanUpdate` (`workflow_graph_canvas.dart:139`) جابه‌جا می‌شوند. در پایان درگ (`onPanEnd`)، متد `savePositions` فراخوانی شده و مختصات تمام گره‌ها در قالب دیکشنری به متد `asoud_erp.api.v1.workflow.update_stage_positions` در `workflow.py:416` ارسال و در دیتابیس ماندگار می‌شود.
7. **انتخاب مرحله:** لمس روی هر گره با رویداد `onTap`، مرحله را انتخاب کرده و بردر ضخیم با رنگ اصلی آسود دور گره هایلایت می‌شود (`workflow_graph_canvas.dart:150`).
8. **باز کردن صفحه تنظیمات مرحله:** انتخاب گره متد `_openStage` در `workflow_designer_page.dart:145` را صدا می‌زند که بسته به نوع گره، کاربر را به صفحات تخصصی (`WorkflowStageSettingsPage`, `StageApprovalPage`, `WorkflowConditionSettingsPage`, `AutomaticActionPage`, `WorkflowWaitSettingsPage`, `WorkflowEndSettingsPage`) هدایت می‌کند.
9. **ذخیره نمودار:** تغییرات ساختاری (درج، حذف مسیر و اتصالات) مستقیماً از طریق API‌های تراکنشی سرور ذخیره می‌شوند. جابه‌جایی هندسی نیز توسط `update_stage_positions` در سرور ثبت می‌گردد.
10. **بازیابی نمودار:** هنگام ورود به طراح، متد `load` در `WorkflowDesignerCubit:38` اجرا شده و ساختار گراف را از متد `asoud_erp.api.v1.workflow.get_workflow_design` (`workflow.py:283`) دریافت و بازسازی می‌کند.
11. **نمایش مسیرهای شرطی:** در ترانزیشن‌های خروجی از مرحله شرط (`Condition`)، سیستم مقدار بولین شرط (`result: true/false`) را شناسایی کرده و رنگ مسیر «شرط برقرار است» را به سبز (`AsoudColors.success`) و «شرط برقرار نیست» را به قرمز (`AsoudColors.danger`) تبدیل می‌کند (`workflow_graph_canvas.dart:278-281`).
12. **نمایش مسیرهای تأیید و رد:** در مرحله تأیید (`Approval`)، متد `WorkflowGraphGeometry.approvalDirection` مسیر تأیید را به سمت راست، رد را به سمت چپ و بازگشت را به سمت پایین متمایل می‌کند و انشعاب بصری تفکیک‌شده ارائه می‌دهد.
13. **بزرگ‌نمایی و کوچک‌نمایی (Zoom):** توسط ویجت `InteractiveViewer` در خطوط ۷۴ تا ۷۸ پیاده‌سازی شده و دامنه زوم با مقادیر صریح `minScale: 0.55` و `maxScale: 2.2` تعریف شده است.
14. **عملکرد در موبایل و ابعاد RTL:** در `workflow_graph_canvas.dart:65-73` با استفاده از `LayoutBuilder`، اندازه صفحه نمایش محاسبه شده و ضریب مقیاس متناسب (`fit`) اعمال می‌شود تا نمودار در عرض‌های مختلف ۳۲۰، ۳۹۰ و ۴۳۰ پیکسل کات‌خوردگی یا Overflow نداشته باشد.
15. **جلوگیری از هم‌پوشانی مراحل (Overlap Prevention):**
    - در چیدمان پیش‌فرض اولیه، مختصات گره‌ها بر اساس فرمول `Offset(155, 40 + (stage.sequence * 175))` محاسبه می‌شود (`workflow_graph_canvas.dart:53`) که فاصله‌ای معادل ۱۷۵ پیکسل عمودی (با ارتفاع گره ۱۱۸ پیکسل) دارد و هم‌پوشانی ندارد.
    - **نقص مهم:** هنگامی که کاربر گره‌ها را با لمس جابه‌جا می‌کند، **هیچ مکانیزم ممانعت از هم‌پوشانی (Collision Detection یا Snap-to-Grid یا Force-directed layout)** در فرانت‌اند وجود ندارد. کاربر می‌تواند دو گره را دقیقاً روی هم قرار دهد و مختصات آن نیز به سرور ارسال و ذخیره می‌شود؛ سرور نیز در `update_stage_positions` تنها محدوده کلی `[-10000, 10000]` را اعتبارسنجی می‌کند.

---

### ۲.۹. تطبیق دقیق اشکال هندسی، رنگ‌ها و عناوین مراحل

جدول زیر تطبیق دقیق کدنویسی فرانت‌اند در `WorkflowGraphGeometry.shape` و `workflowStageVisual` با جدول مرجع مصوب طرح در بند ۹ پلن ممیزی را نشان می‌دهد:

| نوع مرحله در سیستم | شکل هندسی در طراحی مصوب | شکل هندسی در کد فرانت‌اند | رنگ در طراحی مصوب | رنگ در کد فرانت‌اند (ثابت و کد هگز) | عنوان در طراحی مصوب | عنوان واقعی در کد ویجت | وضعیت تطابق |
|---|---|---|---|---|---|---|---|
| **شروع فرایند** (`Start`) | دایره | دایره کامل (`Path()..addOval` بر مبنای `min(w,h)/2`) | سبز | `AsoudColors.success` (`0xFF0B6B3A`) | شروع فرایند | «شروع گردش سند» (`workflow_graph_canvas.dart:367`) | **مطابق در شکل و رنگ**؛ عنوان تفاوت جزیی معنادار دارد. |
| **وظیفه کاربر** (`User Task`) | مستطیل گوشه‌گرد | مستطیل گوشه‌گرد (`addRRect` با `Radius.circular(16)`) | آبی | `AsoudColors.primary` (`0xFF1769F6`) | وظیفه کاربر | «بررسی یا ویرایش سند» (`workflow_graph_canvas.dart:372`) | **مطابق در شکل و رنگ**؛ در بک‌اند `STAGE_TITLES` عنوان «اقدام کاربر» است. |
| **تأیید یا رد** (`Approval`) | شش‌ضلعی | شش‌ضلعی متقارن افقی (`addPolygon` با ۶ راس در خطوط ۲۱-۲۶) | بنفش | `AsoudColors.purple` (`0xFF7C24E8`) | تأیید یا رد | «تأیید، رد یا بازگشت» (`workflow_graph_canvas.dart:377`) | **مطابق در شکل و رنگ**؛ عنوان بسط‌یافته است. |
| **شرط و مسیر** (`Condition`) | لوزی | لوزی ۴ راسه (`addPolygon` با ۴ نقطه میانی در خطوط ۲۹-۳۲) | طلایی | کد رنگ ثابت `Color(0xffBA8427)` (طلایی خردلی) | شرط و مسیر | «تصمیم و انشعاب» (`workflow_graph_canvas.dart:382`) | **مطابق در شکل و رنگ**؛ عنوان در بک‌اند «شرط و مسیر» است. |
| **اقدام خودکار** (`System Action`) | متوازی‌الاضلاع | متوازی‌الاضلاع با زاویه ۱۴ درصد عرض (`addPolygon` در خط ۳۵) | فیروزه‌ای | `AsoudColors.cyan` (`0xFF12B8C4`) | اقدام خودکار | «عملیات سیستمی» (`workflow_graph_canvas.dart:387`) | **مطابق در شکل و رنگ**؛ در بک‌اند «اقدام خودکار» است. |
| **انتظار و زمان‌بندی** (`Wait`) | کپسول | کپسول افقی (`addRRect` با شعاع `Radius.circular(h / 2)`) | خاکستری | `AsoudColors.muted` (`0xFF5B6478`) | انتظار و زمان‌بندی | «انتظار زمان‌بندی‌شده» (`workflow_graph_canvas.dart:392`) | **مطابق در شکل و رنگ**. |
| **پایان فرایند** (`End`) | هشت‌ضلعی | هشت‌ضلعی منتظم (`_octagon` با برش زاویه `cut = side / (2+sqrt(2))`) | قرمز | `AsoudColors.danger` (`0xFFB3261E`) | پایان فرایند | «پایان گردش سند» (`workflow_graph_canvas.dart:397`) | **مطابق در شکل و رنگ**؛ عنوان در بک‌اند «پایان فرایند» است. |

- **بررسی رنگ خطوط اتصال (Connectors):**
  - خطوط اتصال در `workflow_graph_canvas.dart:258` با ثابت `AsoudColors.primary.withValues(alpha: .55)` با ضخامت ۲ پیکسل رسم می‌شوند که دقیقاً بر پایه رنگ آبی اصلی آسود (`#1769F6`) است و کاملاً با الزامات مصوب مطابقت دارد. در مسیرهای خروجی از گره شرط، رنگ خط به تفکیک برقرار (سبز `#0B6B3A`) یا برقرار نیست (قرمز `#B3261E`) تغییر می‌کند.

---

### ۲.۱۰. مدیریت اتصال و حذف مرحله (کنترل آیکون زنجیر روی مسیرها)

۱. **وجود آیکون زنجیر:** در وسط هر خط اتصال (ترانزیشن)، یک نشانگر دایره‌ای سفید با بوردر آبی و آیکون `Icons.link_rounded` قرار گرفته است (`workflow_graph_canvas.dart:109-130`). این کنترل دارای `Tooltip` با متن «مدیریت مسیر» است.
۲. **کنترل‌های بازشونده با لمس:** با لمس این دکمه، منوی `PopupMenuButton` باز می‌شود که شامل دو گزینه است:
   - `+ افزودن مرحله` (مقدار `add`)
   - `− حذف مسیر` (مقدار `remove`)
۳. **مکانیزم درج مرحله بین‌راهی (`insert_workflow_stage`):**
   - با انتخاب `+ افزودن مرحله`، شیت انتخاب نوع مرحله باز می‌شود (`workflow_designer_page.dart:302`).
   - پس از انتخاب، متد `paths(context).insert` فراخوانی شده که API بک‌اند `asoud_erp.api.v1.workflow.insert_workflow_stage` (`workflow.py:533`) را صدا می‌زند.
   - این متد ترانزیشن قدیمی را حذف کرده و دو ترانزیشن جدید ایجاد می‌کند: از مبدا به مرحله جدید (با حفظ شرط و لیبل قبلی) و از مرحله جدید به مقصد قبلی (با اکشن `Continue`). همچنین یک کلید بازگردانی رمزنگاری‌شده (`insertion_token`) برمی‌گرداند.
۴. **لغو و بازگردانی مرحله درج‌شده (`discard_inserted_stage`):**
   - اگر کاربر پس از باز شدن تنظیمات مرحله جدید، آن را ذخیره نکند یا دکمه بازگشت را بزند، بلاک `finally` در `workflow_designer_page.dart:326` تابع `discard` را صدا می‌زند.
   - بک‌اند در `workflow_paths.py:71` توکن رمزگذاری‌شده را رمزگشایی کرده و چنانچه اعتبار زمانی ۲۴ ساعته آن برقرار باشد و گره یا مسیر دیگری تغییر نکرده باشد، مرحله درج‌شده و اتصالات موقت را حذف کرده و ترانزیشن اولیه را عینا بازسازی می‌کند.
۵. **حذف مسیر و شاخه‌های اختصاصی (`remove_path`):**
   - با انتخاب گزینه «− حذف مسیر»، ابتدا پیش‌نمایش حذف با `preview_path_removal` (`workflow_paths.py:44`) دریافت می‌شود.
   - سپس یک دیالوگ تأیید نمایش داده می‌شود (`workflow_designer_page.dart:347`) که صراحتاً به کاربر اعلام می‌کند چه مراحلی به صورت اختصاصی حذف خواهند شد و چه مراحلی مشترک باقی می‌مانند.
   - با تأیید کاربر، متد `remove_path` در `workflow_paths.py:50` با تطابق شماره نسخه گراف (`version`) مراحل و اتصالات یتیم‌شده را به صورت امن و در یک Savepoint دیتابیسی حذف می‌نماید.

---

### ۲.۱۱. صحت ساختار نمودار و اعتبارسنجی قوانین گراف در سرور

اعتبارسنجی ساختار گراف گردش‌کار در دو سطح انجام می‌شود:
- سطح اول: پیش‌نیازهای فعال‌سازی فرایند (`activation_requirements` در `asoud_erp/services/workflow_contract.py:65`)
- سطح دوم: اعتبارسنجی جامع و تحلیل گراف (`validate_workflow` در `asoud_erp/services/workflow_check.py:106`)

#### جدول نگاشت ۱۲ قانون ساختاری به اعتبارسنجی‌های سرور:
| شماره | عنوان قانون ساختاری در پلن | وضعیت در معماری سیستم | تابع مالک اعتبارسنجی | فایل و شماره خط در بک‌اند | پیام خطای سرور یا کد ایراد |
|---|---|---|---|---|---|
| ۱ | مرحله شروع معتبر | خطای اعتبارسنجی (باید دقیقاً ۱ شروع باشد) | `activation_requirements` | `workflow_contract.py:71-72` | «گردش‌کار باید یک شروع و دست‌کم یک پایان داشته باشد.» (`start_end_missing`) |
| ۲ | مرحله پایان معتبر | خطای اعتبارسنجی (حداقل یک پایان) | `activation_requirements` | `workflow_contract.py:71-72` | همان پیام بالا در صورت نبود گره End |
| ۳ | مراحل بدون ورودی (Orphan) | خطای اعتبارسنجی (تمام مراحل باید از شروع قابل دسترسی باشند) | `activation_requirements` | `workflow_contract.py:90-104` | `DISCONNECTED_PATHS`: «همهٔ مراحل باید از شروع قابل دسترس و به یک پایان متصل باشند.» |
| ۴ | مراحل بدون خروجی (Dead-end) | خطای اعتبارسنجی (تمام مراحل به جز End باید خروجی داشته باشند) | `activation_requirements` | `workflow_contract.py:97-104` | همان پیام خطای `DISCONNECTED_PATHS` |
| ۵ | اتصالات ناقص / ارجاع به خارج | خطای اعتبارسنجی مسدودکننده | `activation_requirements` | `workflow_contract.py:75-77` | «یکی از مسیرها به مرحله‌ای خارج از این گردش‌کار متصل است.» (`route_external`) |
| ۶ | اتصالات تکراری به یک مقصد | خطای اعتبارسنجی در ایجاد ترانزیشن | `connect_workflow_stages` | `workflow.py:476` و `503` | «این اقدام در حال حاضر دارای یک مسیر از مرحله انتخاب‌شده است» / «مسیرهای خروجی شرط تکراری یا نامعتبرند» |
| ۷ | مسیرهای غیرقابل‌دسترس | خطای اعتبارسنجی مسدودکننده فعال‌سازی | `activation_requirements` | `workflow_contract.py:103` | خطای `DISCONNECTED_PATHS` |
| ۸ | حلقه‌های نامعتبر (حلقه بسته بدون خروج) | هشدار یا خطای شیت اعتبارسنجی | `validate_workflow` | `workflow_check.py:120` و `124` | `loop_no_exit` (خطا): «مرحله در حلقه‌ای قرار دارد که راهی به پایان ندارد»؛ `self_loop` (هشدار): اتصال گره به خودش |
| ۹ | خروجی‌های بدون مقصد منتهی به پایان | خطای اعتبارسنجی مسدودکننده | `activation_requirements` | `workflow_contract.py:97-104` | خطای `DISCONNECTED_PATHS` |
| ۱۰ | اتصال به مرحله حذف‌شده | خطای اعتبارسنجی مسدودکننده | `workflow_paths.py:32` | `workflow_paths.py:32` | «مسیر انتخاب‌شده دیگر موجود یا معتبر نیست؛ نمودار را تازه کنید.» |
| ۱۱ | مسیرهای شرطی ناقص | خطای اعتبارسنجی مسدودکننده | `_validate_saved_routes` | `workflow_contract.py:41-44` | «تنظیمات یا مسیر خروج یکی از مراحل کامل و معتبر نیست.» (گره شرط باید دقیقاً ۲ مسیر خروجی با مقادیر مجزای True و False داشته باشد) |
| ۱۲ | اتصال خروجی از مرحله پایان | خطای اعتبارسنجی مسدودکننده | `connect_workflow_stages` | `workflow.py:499` و `workflow_contract.py:38-40` | «مرحله پایان نمی‌تواند مسیر خروجی داشته باشد.» (`The end stage cannot have an outgoing route`) |

---


## جمع‌بندی محدودهٔ صفحه‌ها

جدول معماری صفحات درخواست عمومی، کارتابل، وظایف، جزئیات نمونه، تنظیمات هفت مرحله و فرم‌ساز را نیز در 37 مشخص می‌کند. رفتارهای کارتابل و نوار تصمیم در 42 و همهٔ اشکال/رنگ‌ها و زنجیر بوم در همین سند آمده‌اند. زنجیر مدیریت مسیر با عملیات Link Record اقدام خودکار یکی نیست. عناوین متفاوت مراحل در A1-014 و A2-008 محفوظ‌اند و هندسهٔ صحیح آن‌ها این نقص‌های نام‌گذاری را منتفی نمی‌کند.

