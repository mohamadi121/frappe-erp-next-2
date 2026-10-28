# سربرگ تاریخی اسناد منابع انسانی

این قرارداد برای `employment_contracts.get_contract` و `get_contract_print`،
`hiring_orders.print_hiring_order`، `employment_certificates.get_certificate`،
`personnel_introduction_letters.get_letter/print_letter` و
`salary_change_orders.print_salary_change_order` است؛ نقش‌ها، شرکت و کنترل حقوق هر ماژول همچنان اعمال می‌شوند.

پاسخ `data.letterhead_missing` یک مقدار بولی است؛ قرارداد کار همین مقدار را در `print_payload` نیز دارد.
برای سند نهایی قدیمی که کلید snapshot سربرگ ندارد، مقدار `true` است و چاپ با متن، شماره و مقادیر تاریخی سند، بدون سربرگ نمایش داده می‌شود.
سربرگ جاری شرکت هرگز برای سند نهایی بازیابی یا در سند ذخیره نمی‌شود. مقدار صریح `null` در snapshot به معنی صدور بدون سربرگ است و `letterhead_missing: false` دارد.
پیش‌نویس از سربرگ جاری استفاده می‌کند و پرچم آن `false` است. در نهایی‌سازی حکم استخدام نیز snapshot سربرگ ثبت می‌شود.
این تغییر افزایشی است و migration ندارد؛ هیچ سند قدیمی بازنویسی نمی‌شود.
