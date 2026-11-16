"""The single system vocabulary of module keys.

Every layer that names a module — workflow definitions, document templates and
the app — uses the same keys. Earlier the workflow engine and the document
templates each kept their own list (``Accounting``/``Sales``/``Inventory``/
``Support`` vs ``Finance``/``Selling``/``Stock``/``Admin``), so a saved
workflow had to be re-mapped by hand before it reached the templates. This
module is the one reference; the legacy workflow keys are still accepted and
normalized so existing records keep loading.
"""

# The canonical module keys, in the order the app should show them.
MODULE_KEYS = ("Finance", "Purchase", "Selling", "Stock", "HR", "Admin", "IT")

MODULE_LABELS = {
    "Finance": "مالی",
    "Purchase": "خرید",
    "Selling": "فروش",
    "Stock": "انبار",
    "HR": "منابع انسانی",
    "Admin": "خدمات اداری",
    "IT": "IT و تجهیزات",
}

MODULE_DESCRIPTIONS = {
    "Finance": "حسابداری و خزانه‌داری",
    "Purchase": "تأمین کالا و خدمات",
    "Selling": "مدیریت فروش و مشتریان",
    "Stock": "مدیریت موجودی کالا",
    "HR": "کارکنان و حقوق",
    "Admin": "خدمات رفاهی و اداری",
    "IT": "تجهیزات و زیرساخت",
}

# Legacy workflow-definition keys -> canonical key. Both old vocabularies stay
# readable: a stored or submitted legacy key resolves to its canonical key.
LEGACY_MODULE_KEYS = {
    "Accounting": "Finance",
    "Sales": "Selling",
    "Inventory": "Stock",
    "Support": "Admin",
}


def normalize_module_key(key):
    """Return the canonical key for ``key`` (canonical or legacy), else ``None``."""
    if key in MODULE_KEYS:
        return key
    return LEGACY_MODULE_KEYS.get(key)
