from __future__ import annotations

from copy import deepcopy
import os
import secrets
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.catalog_repo import CatalogRepo
from models import Brand, Category, Product, Tenant, TenantMembership, TenantSettings, User, UserRole
from models.users import normalize_role


DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_TITLE = "Main Store"

_DEFAULT_BUTTON_LABELS = {
    "catalog": "🛍 Каталог",
    "cart": "🛒 Корзина",
    "orders": "📦 Заказы",
    "ai": "✨ AI-Консультант",
    "support": "💬 Поддержка",
}

_DEFAULT_CLIENT_MENU = [
    ["🛍 Каталог", "🛒 Корзина"],
    ["📦 Заказы", "✨ AI-Консультант"],
    ["💬 Продавец", "💬 Владелец"],
]

_DEFAULT_STAFF_MENU = [
    ["🛍 Каталог", "📋 Заказы"],
    ["💳 Касса"],
]

_DEFAULT_OWNER_MENU = [
    ["📦 Товары", "📊 Склад"],
    ["📋 Заказы", "📈 Статистика"],
    ["✨ AI-Консультант", "🔙 Отмена"],
]

TENANT_PRESETS: dict[str, dict[str, object]] = {
    "fashion": {
        "title": "Fashion Store",
        "description": "Одежда, обувь и аксессуары с фокусом на подбор образа.",
        "support_label": "Стилист",
        "button_labels": {
            "catalog": "👗 Коллекция",
            "cart": "👜 Корзина",
            "orders": "📦 Заказы",
            "ai": "✨ Подобрать образ",
            "support": "💬 Стилист",
        },
        "welcome_text_client": "Добро пожаловать! Выберите коллекцию или попросите стилиста подобрать образ.",
        "welcome_text_staff": "Fashion-терминал готов. Проверьте заказы и наличие размеров.",
        "welcome_text_owner": "Панель fashion-магазина готова к работе.",
        "category_names": ["Платья", "Костюмы", "Обувь", "Аксессуары"],
        "brand_names": ["Atelier Line", "Urban Tailor", "Silk Avenue"],
        "demo_products": [
            {
                "title": "Шелковое платье Aurora",
                "description": "Легкое вечернее платье из шелка с акцентом на сезонную капсулу.",
                "category_name": "Платья",
                "brand_name": "Atelier Line",
                "purchase_price": 12000.0,
                "sale_price": 24900.0,
                "size": "S",
                "quantity": 4,
            },
            {
                "title": "Кожаные лоферы Midtown",
                "description": "Премиальные лоферы для smart casual образов.",
                "category_name": "Обувь",
                "brand_name": "Urban Tailor",
                "purchase_price": 9500.0,
                "sale_price": 18900.0,
                "size": "42",
                "quantity": 6,
            },
        ],
    },
    "flowers": {
        "title": "Flower Boutique",
        "description": "Букеты, композиции и срочная доставка цветов.",
        "support_label": "Флорист",
        "button_labels": {
            "catalog": "💐 Букеты",
            "cart": "🧺 Корзина",
            "orders": "🚚 Доставка",
            "ai": "✨ Подобрать букет",
            "support": "💬 Флорист",
        },
        "welcome_text_client": "Добро пожаловать в flower boutique. Подберем букет под повод и бюджет.",
        "welcome_text_staff": "Рабочее место флориста готово. Следите за срочными доставками.",
        "welcome_text_owner": "Панель цветочного магазина готова к работе.",
        "category_names": ["Монобукеты", "Композиции", "Свадебные", "Подарки"],
        "brand_names": ["Rose Studio", "Peony Lab", "Bloom Craft"],
        "demo_products": [
            {
                "title": "Букет White Peony",
                "description": "Премиальный букет из пионов для подарка и свадебных событий.",
                "category_name": "Монобукеты",
                "brand_name": "Peony Lab",
                "purchase_price": 1800.0,
                "sale_price": 3900.0,
                "size": "standard",
                "quantity": 12,
            },
            {
                "title": "Композиция Bloom Box",
                "description": "Коробка-композиция с сезонными цветами и открыткой.",
                "category_name": "Композиции",
                "brand_name": "Bloom Craft",
                "purchase_price": 2200.0,
                "sale_price": 4700.0,
                "size": "box",
                "quantity": 8,
            },
        ],
    },
    "watches": {
        "title": "Luxury Watch House",
        "description": "Премиальные часы, лимитированные коллекции и персональный консультант.",
        "support_label": "Консьерж",
        "button_labels": {
            "catalog": "⌚ Коллекция",
            "cart": "🧾 Резерв",
            "orders": "📦 Заказы",
            "ai": "✨ Подобрать часы",
            "support": "💬 Консьерж",
        },
        "welcome_text_client": "Добро пожаловать. Мы поможем подобрать часы под стиль, бюджет и статус.",
        "welcome_text_staff": "Watch desk активен. Контролируйте резервы и VIP-запросы.",
        "welcome_text_owner": "Панель watch-бутика готова к работе.",
        "category_names": ["Dress Watches", "Sport Watches", "Limited Edition", "Accessories"],
        "brand_names": ["Chronos Atelier", "Maison du Temps", "Aurum Geneva"],
        "demo_products": [
            {
                "title": "Chronos Atelier Heritage",
                "description": "Классические dress watches с автоматическим механизмом.",
                "category_name": "Dress Watches",
                "brand_name": "Chronos Atelier",
                "purchase_price": 185000.0,
                "sale_price": 269000.0,
                "size": "40mm",
                "quantity": 2,
            },
            {
                "title": "Aurum Geneva Diver One",
                "description": "Спортивная модель с повышенной водозащитой и керамическим безелем.",
                "category_name": "Sport Watches",
                "brand_name": "Aurum Geneva",
                "purchase_price": 210000.0,
                "sale_price": 315000.0,
                "size": "42mm",
                "quantity": 3,
            },
        ],
    },
}


def _build_default_tenant_settings(tenant_id: int) -> TenantSettings:
    return TenantSettings(
        tenant_id=tenant_id,
        storefront_title=DEFAULT_TENANT_TITLE,
        support_label="Поддержка",
        owner_title="Владелец",
        staff_title="Сотрудник",
        welcome_text_client="Привет! Выбери действие:",
        welcome_text_staff="Привет! Твой рабочий терминал готов.",
        welcome_text_owner="Привет! Выбери действие:",
        button_labels=deepcopy(_DEFAULT_BUTTON_LABELS),
        menu_client=deepcopy(_DEFAULT_CLIENT_MENU),
        menu_staff=deepcopy(_DEFAULT_STAFF_MENU),
        menu_owner=deepcopy(_DEFAULT_OWNER_MENU),
        ui_theme={},
        ai_settings={},
    )


def list_tenant_presets() -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for key, value in TENANT_PRESETS.items():
        row = deepcopy(value)
        row["key"] = key
        items.append(row)
    return items


def get_tenant_preset(preset_key: str | None) -> dict[str, object] | None:
    if not preset_key:
        return None
    preset = TENANT_PRESETS.get((preset_key or "").strip().lower())
    if preset is None:
        return None
    return deepcopy(preset)


async def _ensure_named_categories(session: AsyncSession, tenant_id: int, names: list[str]) -> None:
    for name in names:
        normalized = (name or "").strip()
        if not normalized:
            continue
        stmt = select(Category.id).where(Category.tenant_id == tenant_id, Category.name == normalized)
        existing = await session.scalar(stmt)
        if existing is None:
            session.add(Category(tenant_id=tenant_id, name=normalized))
    await session.flush()


async def _ensure_named_brands(session: AsyncSession, tenant_id: int, names: list[str]) -> None:
    for name in names:
        normalized = (name or "").strip()
        if not normalized:
            continue
        stmt = select(Brand.id).where(Brand.tenant_id == tenant_id, Brand.name == normalized)
        existing = await session.scalar(stmt)
        if existing is None:
            session.add(Brand(tenant_id=tenant_id, name=normalized))
    await session.flush()


async def seed_tenant_demo_products(session: AsyncSession, tenant: Tenant, preset_key: str) -> int:
    preset = get_tenant_preset(preset_key)
    if preset is None:
        raise ValueError(f"Unknown tenant preset: {preset_key}")

    created_count = 0
    repo = CatalogRepo(session, tenant_id=tenant.id)
    for row in list(preset.get("demo_products", [])):
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        existing_stmt = select(Product.id).where(Product.tenant_id == tenant.id, Product.title == title)
        existing_product = await session.scalar(existing_stmt)
        if existing_product is not None:
            continue

        category = await repo.get_or_create_category(str(row.get("category_name") or "General"))
        brand = await repo.get_or_create_brand(str(row.get("brand_name") or "Store Brand"))
        product = await repo.create_product(
            title=title,
            description=str(row.get("description") or "").strip() or None,
            purchase_price=float(row.get("purchase_price") or 0),
            sale_price=float(row.get("sale_price") or 0),
            category=category,
            brand=brand,
        )
        await repo.add_stock(
            product,
            size=str(row.get("size") or "standard"),
            quantity=int(row.get("quantity") or 0),
        )
        created_count += 1

    await session.flush()
    return created_count


async def apply_tenant_preset(
    session: AsyncSession,
    tenant: Tenant,
    preset_key: str,
    *,
    overwrite: bool = True,
) -> TenantSettings:
    preset = get_tenant_preset(preset_key)
    if preset is None:
        raise ValueError(f"Unknown tenant preset: {preset_key}")

    settings_row = await get_or_create_tenant_settings(session, tenant.id)
    button_labels = deepcopy(settings_row.button_labels or _DEFAULT_BUTTON_LABELS)
    button_labels.update({str(k): str(v) for k, v in dict(preset.get("button_labels", {})).items()})

    if overwrite or not (tenant.title or "").strip():
        tenant.title = str(preset.get("title") or tenant.title)
    settings_row.storefront_title = tenant.title
    settings_row.support_label = str(preset.get("support_label") or settings_row.support_label)
    settings_row.welcome_text_client = str(preset.get("welcome_text_client") or settings_row.welcome_text_client)
    settings_row.welcome_text_staff = str(preset.get("welcome_text_staff") or settings_row.welcome_text_staff)
    settings_row.welcome_text_owner = str(preset.get("welcome_text_owner") or settings_row.welcome_text_owner)
    settings_row.button_labels = button_labels

    category_names = [str(item) for item in list(preset.get("category_names", []))]
    brand_names = [str(item) for item in list(preset.get("brand_names", []))]
    await _ensure_named_categories(session, tenant.id, category_names)
    await _ensure_named_brands(session, tenant.id, brand_names)
    await session.flush()
    return settings_row


async def ensure_default_tenant(session: AsyncSession) -> Tenant:
    env_bot_token = os.getenv("BOT_TOKEN", "").strip()
    env_admin_key = os.getenv("WEB_ADMIN_KEY", "").strip()

    stmt = select(Tenant).where(Tenant.slug == DEFAULT_TENANT_SLUG)
    res = await session.execute(stmt)
    tenant = res.scalar_one_or_none()

    if tenant is None:
        default_bot_token = env_bot_token or None
        default_admin_key = env_admin_key or None

        if env_bot_token:
            existing_bot_token_stmt = select(Tenant.id).where(Tenant.bot_token == env_bot_token)
            existing_bot_token_owner = await session.scalar(existing_bot_token_stmt)
            if existing_bot_token_owner is not None:
                default_bot_token = None

        if env_admin_key:
            existing_admin_key_stmt = select(Tenant.id).where(Tenant.admin_api_key == env_admin_key)
            existing_admin_key_owner = await session.scalar(existing_admin_key_stmt)
            if existing_admin_key_owner is not None:
                default_admin_key = None

        tenant = Tenant(
            slug=DEFAULT_TENANT_SLUG,
            title=DEFAULT_TENANT_TITLE,
            status="active",
            bot_token=default_bot_token,
            admin_api_key=default_admin_key,
        )
        session.add(tenant)
        await session.flush()
    else:
        if env_bot_token and not tenant.bot_token:
            existing_bot_token_stmt = select(Tenant.id).where(
                Tenant.bot_token == env_bot_token,
                Tenant.id != tenant.id,
            )
            existing_bot_token_owner = await session.scalar(existing_bot_token_stmt)
            if existing_bot_token_owner is None:
                tenant.bot_token = env_bot_token
        if env_admin_key and not tenant.admin_api_key:
            existing_admin_key_stmt = select(Tenant.id).where(
                Tenant.admin_api_key == env_admin_key,
                Tenant.id != tenant.id,
            )
            existing_admin_key_owner = await session.scalar(existing_admin_key_stmt)
            if existing_admin_key_owner is None:
                tenant.admin_api_key = env_admin_key

    settings_stmt = select(TenantSettings).where(TenantSettings.tenant_id == tenant.id)
    settings_res = await session.execute(settings_stmt)
    tenant_settings = settings_res.scalar_one_or_none()
    if tenant_settings is None:
        session.add(_build_default_tenant_settings(tenant.id))
        await session.flush()

    return tenant


async def get_or_create_tenant_settings(session: AsyncSession, tenant_id: int) -> TenantSettings:
    stmt = select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
    res = await session.execute(stmt)
    tenant_settings = res.scalar_one_or_none()
    if tenant_settings is not None:
        return tenant_settings

    tenant_settings = _build_default_tenant_settings(tenant_id)
    session.add(tenant_settings)
    await session.flush()
    return tenant_settings


async def ensure_tenant_membership(
    session: AsyncSession,
    user: User,
    tenant_id: int,
    default_role: str,
) -> TenantMembership:
    stmt = select(TenantMembership).where(
        TenantMembership.tenant_id == tenant_id,
        TenantMembership.user_id == user.id,
    )
    res = await session.execute(stmt)
    membership = res.scalar_one_or_none()
    if membership is None:
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=user.id,
            role=normalize_role(default_role),
        )
        session.add(membership)
        await session.flush()
    return membership


async def ensure_default_user_membership(
    session: AsyncSession,
    user: User,
    default_role: str,
) -> TenantMembership:
    tenant = await ensure_default_tenant(session)
    if user.tenant_id is None:
        user.tenant_id = tenant.id
        await session.flush()
    return await ensure_tenant_membership(session, user, tenant.id, default_role)


async def create_tenant_with_defaults(
    session: AsyncSession,
    *,
    slug: str,
    title: str,
    domain: str | None = None,
    bot_token: str | None = None,
    admin_api_key: str | None = None,
    owner_tg_id: int | None = None,
    owner_username: str | None = None,
    owner_first_name: str | None = None,
    owner_last_name: str | None = None,
) -> tuple[Tenant, TenantSettings, User | None]:
    tenant = Tenant(
        slug=(slug or "").strip().lower(),
        title=(title or "").strip(),
        status="active",
        domain=_extract_host(domain) or None,
        bot_token=(bot_token or "").strip() or None,
        admin_api_key=(admin_api_key or "").strip() or secrets.token_urlsafe(24),
    )
    session.add(tenant)
    await session.flush()

    tenant_settings = _build_default_tenant_settings(tenant.id)
    tenant_settings.storefront_title = tenant.title
    session.add(tenant_settings)
    await session.flush()

    owner_user: User | None = None
    if owner_tg_id is not None:
        stmt = select(User).where(User.tg_id == owner_tg_id)
        res = await session.execute(stmt)
        owner_user = res.scalar_one_or_none()
        if owner_user is None:
            owner_user = User(
                tg_id=owner_tg_id,
                tenant_id=tenant.id,
                username=(owner_username or "").strip() or None,
                first_name=(owner_first_name or "").strip() or None,
                last_name=(owner_last_name or "").strip() or None,
                role=UserRole.OWNER.value,
                ai_quota=0,
            )
            session.add(owner_user)
            await session.flush()
        elif owner_user.tenant_id is None:
            owner_user.tenant_id = tenant.id

        membership = await ensure_tenant_membership(session, owner_user, tenant.id, UserRole.OWNER.value)
        membership.role = UserRole.OWNER.value
        owner_user.role = UserRole.OWNER.value
        await session.flush()

    return tenant, tenant_settings, owner_user


async def get_or_create_default_tenant_user(
    session: AsyncSession,
    *,
    tg_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None = None,
    default_role: str,
    ai_quota: int = 0,
) -> tuple[User, TenantMembership]:
    stmt = select(User).where(User.tg_id == tg_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    tenant = await ensure_default_tenant(session)

    if user is None:
        user = User(
            tg_id=tg_id,
            tenant_id=tenant.id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            role=normalize_role(default_role),
            ai_quota=ai_quota,
        )
        session.add(user)
        await session.flush()
    else:
        if user.tenant_id is None:
            user.tenant_id = tenant.id
        if username and not user.username:
            user.username = username
        if first_name and not user.first_name:
            user.first_name = first_name
        if last_name and not user.last_name:
            user.last_name = last_name
        await session.flush()

    membership = await ensure_tenant_membership(session, user, tenant.id, default_role)
    user.role = normalize_role(membership.role)
    return user, membership


async def get_membership_for_user(
    session: AsyncSession,
    user: User,
    tenant_id: int,
) -> TenantMembership | None:
    stmt = select(TenantMembership).where(
        TenantMembership.tenant_id == tenant_id,
        TenantMembership.user_id == user.id,
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def get_membership_for_tg_id(
    session: AsyncSession,
    tg_id: int,
    tenant_id: int,
) -> TenantMembership | None:
    stmt = (
        select(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .where(User.tg_id == tg_id, TenantMembership.tenant_id == tenant_id)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def sync_user_role_from_memberships(
    session: AsyncSession,
    user: User,
) -> str:
    stmt = select(TenantMembership.role).where(TenantMembership.user_id == user.id)
    res = await session.execute(stmt)
    roles = {normalize_role(role) for role in res.scalars().all()}

    if UserRole.OWNER.value in roles:
        user.role = UserRole.OWNER.value
    elif UserRole.STAFF.value in roles:
        user.role = UserRole.STAFF.value
    else:
        user.role = UserRole.CLIENT.value

    await session.flush()
    return normalize_role(user.role)


async def get_role_for_user(
    session: AsyncSession,
    user: User,
    tenant_id: int,
) -> str:
    membership = await get_membership_for_user(session, user, tenant_id)
    if membership is not None:
        return normalize_role(membership.role)
    return UserRole.CLIENT.value


async def list_tenant_user_ids_by_role(
    session: AsyncSession,
    tenant_id: int,
    role: str,
) -> list[int]:
    stmt = (
        select(User.tg_id)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.role == normalize_role(role),
        )
    )
    res = await session.execute(stmt)
    return [tg_id for tg_id in res.scalars().all() if tg_id]


def build_default_client_role(user_tg_id: int, owner_tg_id: int) -> str:
    return UserRole.OWNER.value if user_tg_id == owner_tg_id else UserRole.CLIENT.value


async def resolve_tenant_by_slug(session: AsyncSession, slug: str | None) -> Tenant | None:
    normalized = (slug or "").strip().lower()
    if not normalized:
        return None
    stmt = select(Tenant).where(Tenant.slug == normalized, Tenant.status == "active")
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def resolve_tenant_by_bot_token(session: AsyncSession, bot_token: str | None) -> Tenant:
    normalized = (bot_token or "").strip()
    if normalized:
        stmt = select(Tenant).where(Tenant.bot_token == normalized, Tenant.status == "active")
        res = await session.execute(stmt)
        tenant = res.scalar_one_or_none()
        if tenant is not None:
            return tenant

    tenant = await ensure_default_tenant(session)
    if normalized and not tenant.bot_token:
        tenant.bot_token = normalized
        await session.flush()
    return tenant


def _extract_host(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        return (urlsplit(raw).hostname or "").lower()
    return raw.split(":", 1)[0].strip().lower()


async def resolve_tenant_by_domain(session: AsyncSession, domain: str | None) -> Tenant | None:
    host = _extract_host(domain)
    if not host:
        return None
    stmt = select(Tenant).where(Tenant.domain == host, Tenant.status == "active")
    res = await session.execute(stmt)
    tenant = res.scalar_one_or_none()
    if tenant is not None:
        return tenant

    subdomain = host.split(".", 1)[0]
    if subdomain and subdomain != host:
        return await resolve_tenant_by_slug(session, subdomain)
    return None


async def resolve_tenant(
    session: AsyncSession,
    *,
    slug: str | None = None,
    domain: str | None = None,
    bot_token: str | None = None,
) -> Tenant:
    tenant = await resolve_tenant_by_slug(session, slug)
    if tenant is not None:
        return tenant
    tenant = await resolve_tenant_by_domain(session, domain)
    if tenant is not None:
        return tenant
    return await resolve_tenant_by_bot_token(session, bot_token)


async def get_runtime_tenant(session: AsyncSession) -> Tenant:
    return await resolve_tenant(session, bot_token=os.getenv("BOT_TOKEN", ""))


async def get_user_by_tg_id(session: AsyncSession, tg_id: int) -> User | None:
    stmt = select(User).where(User.tg_id == tg_id)
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def user_has_tenant_role(
    session: AsyncSession,
    tg_id: int,
    tenant_id: int,
    roles: list[str] | tuple[str, ...],
) -> bool:
    stmt = (
        select(TenantMembership.id)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            User.tg_id == tg_id,
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.role.in_([normalize_role(role) for role in roles]),
        )
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none() is not None


async def get_primary_owner_tg_id(session: AsyncSession, tenant_id: int) -> int | None:
    stmt = (
        select(User.tg_id)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .where(TenantMembership.tenant_id == tenant_id, TenantMembership.role == UserRole.OWNER.value)
        .order_by(User.id.asc())
    )
    res = await session.execute(stmt)
    return res.scalars().first()


async def list_tenant_recipient_ids(
    session: AsyncSession,
    tenant_id: int,
    *,
    include_owner: bool = True,
    include_staff: bool = True,
) -> list[int]:
    roles: list[str] = []
    if include_owner:
        roles.append(UserRole.OWNER.value)
    if include_staff:
        roles.append(UserRole.STAFF.value)
    if not roles:
        return []
    stmt = (
        select(User.tg_id)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.role.in_(roles),
        )
        .order_by(User.id.asc())
    )
    res = await session.execute(stmt)
    return [tg_id for tg_id in res.scalars().all() if tg_id]


async def get_runtime_tenant_role_for_tg_id(session: AsyncSession, tg_id: int) -> str | None:
    tenant = await get_runtime_tenant(session)
    user = await get_user_by_tg_id(session, tg_id)
    if user is None:
        return None
    membership = await get_membership_for_user(session, user, tenant.id)
    if membership is None:
        return None
    return normalize_role(membership.role)


async def is_user_blocked_in_tenant(session: AsyncSession, tg_id: int, tenant_id: int) -> bool:
    membership = await get_membership_for_tg_id(session, tg_id, tenant_id)
    if membership is None:
        return False
    return bool(membership.is_blocked)


async def is_runtime_user_blocked(session: AsyncSession, tg_id: int) -> bool:
    tenant = await get_runtime_tenant(session)
    return await is_user_blocked_in_tenant(session, tg_id, tenant.id)


async def is_runtime_owner(session: AsyncSession, tg_id: int) -> bool:
    role = await get_runtime_tenant_role_for_tg_id(session, tg_id)
    return role == UserRole.OWNER.value


async def is_runtime_owner_or_staff(session: AsyncSession, tg_id: int) -> bool:
    role = await get_runtime_tenant_role_for_tg_id(session, tg_id)
    return role in {UserRole.OWNER.value, UserRole.STAFF.value}