from __future__ import annotations

from pathlib import Path
from decimal import Decimal
from collections import Counter
import re
import logging
import secrets
import threading
import uuid
from html import escape
import os
import time
from datetime import datetime

from utils.trace import get_trace_id, new_trace_id, set_trace_id

import aiohttp
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
from sqlalchemy import func, select, text, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from redis.exceptions import RedisError

from config import settings
from database.db_manager import async_session_maker
from database.orders_repo import OrdersRepo
from database.catalog_repo import CatalogRepo
from models import Brand, CartItem, Category, Product, ProductStock, User, UserRole
from models import Tenant, TenantMembership, TenantSettings
from utils.tenants import (
    _extract_host,
    apply_tenant_preset,
    create_tenant_with_defaults,
    ensure_default_tenant,
    ensure_tenant_membership,
    get_primary_owner_tg_id,
    get_or_create_tenant_settings,
    get_tenant_preset,
    list_tenant_presets,
    resolve_tenant,
    seed_tenant_demo_products,
)
from utils.erp_report import build_erp_report_xlsx
from schemas import ProductResponse, WebOrderRequest, WebOrderResponse
from schemas import WebAIChatRequest, WebAIChatResponse
from schemas import (
    AdminBulkProvisionResultRow,
    AdminBulkProvisionTenantItem,
    AdminBulkProvisionTenantsRequest,
    AdminBulkProvisionTenantsResponse,
    AdminCreateTenantRequest,
    AdminCreateTenantResponse,
    AdminCreateProductRequest,
    AdminCreateProductResponse,
    AdminMetaResponse,
    AdminProductRow,
    AdminProductsResponse,
    AdminUpdateProductRequest,
    AdminDeleteProductResponse,
    AdminTenantSettingsResponse,
    AdminTenantSettingsUpdateRequest,
    AdminTenantPresetRow,
    AdminTenantPresetsResponse,
    AdminTenantRow,
    AdminTenantsResponse,
    ProductMediaResponse,
    TenantSmokeResponse,
)

def _load_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        raise RuntimeError("CORS_ORIGINS must be set to a comma-separated whitelist of allowed origins")

    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if not origins:
        raise RuntimeError("CORS_ORIGINS must contain at least one valid origin")
    if any(origin == "*" for origin in origins):
        raise RuntimeError("Wildcard '*' is not allowed in CORS_ORIGINS")
    return origins


_CORS_ORIGINS: list[str] = _load_cors_origins()
_RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "120"))
_RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
_METRIC_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_METRICS_LOCK = threading.Lock()
_STARTED_AT_TS = time.time()
_HTTP_REQUESTS_TOTAL: Counter[tuple[str, str, str]] = Counter()
_HTTP_REQUEST_DURATION_BUCKET: Counter[tuple[str, str, str]] = Counter()
_HTTP_REQUEST_DURATION_SUM: dict[tuple[str, str], float] = {}
_HTTP_REQUEST_DURATION_COUNT: Counter[tuple[str, str]] = Counter()


def _normalize_metric_path(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if route_path:
        return str(route_path)
    return request.url.path


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _observe_http_metrics(method: str, path: str, status_code: int, duration_sec: float) -> None:
    status = str(status_code)
    with _METRICS_LOCK:
        _HTTP_REQUESTS_TOTAL[(method, path, status)] += 1
        _HTTP_REQUEST_DURATION_SUM[(method, path)] = _HTTP_REQUEST_DURATION_SUM.get((method, path), 0.0) + duration_sec
        _HTTP_REQUEST_DURATION_COUNT[(method, path)] += 1

        for bucket in _METRIC_BUCKETS:
            if duration_sec <= bucket:
                _HTTP_REQUEST_DURATION_BUCKET[(method, path, str(bucket))] += 1
        _HTTP_REQUEST_DURATION_BUCKET[(method, path, "+Inf")] += 1


def _render_prometheus_metrics() -> str:
    lines: list[str] = []

    with _METRICS_LOCK:
        req_total = _HTTP_REQUESTS_TOTAL.copy()
        hist_bucket = _HTTP_REQUEST_DURATION_BUCKET.copy()
        hist_sum = _HTTP_REQUEST_DURATION_SUM.copy()
        hist_count = _HTTP_REQUEST_DURATION_COUNT.copy()

    lines.append("# HELP app_uptime_seconds Application uptime in seconds")
    lines.append("# TYPE app_uptime_seconds gauge")
    lines.append(f"app_uptime_seconds {time.time() - _STARTED_AT_TS:.6f}")

    lines.append("# HELP app_http_requests_total Total HTTP requests")
    lines.append("# TYPE app_http_requests_total counter")
    for (method, path, status), total_value in sorted(req_total.items()):
        lines.append(
            f'app_http_requests_total{{method="{_escape_label(method)}",path="{_escape_label(path)}",status="{_escape_label(status)}"}} {total_value}'
        )

    lines.append("# HELP app_http_request_duration_seconds HTTP request latency histogram")
    lines.append("# TYPE app_http_request_duration_seconds histogram")
    for (method, path, le), bucket_value in sorted(hist_bucket.items()):
        lines.append(
            f'app_http_request_duration_seconds_bucket{{method="{_escape_label(method)}",path="{_escape_label(path)}",le="{_escape_label(le)}"}} {bucket_value}'
        )
    for (method, path), duration_sum in sorted(hist_sum.items()):
        lines.append(
            f'app_http_request_duration_seconds_sum{{method="{_escape_label(method)}",path="{_escape_label(path)}"}} {duration_sum:.6f}'
        )
    for (method, path), duration_count in sorted(hist_count.items()):
        lines.append(
            f'app_http_request_duration_seconds_count{{method="{_escape_label(method)}",path="{_escape_label(path)}"}} {duration_count}'
        )

    return "\n".join(lines) + "\n"


async def _render_tenant_prometheus_metrics() -> str:
    lines = [
        "# HELP app_tenant_products_total Total products per tenant",
        "# TYPE app_tenant_products_total gauge",
        "# HELP app_tenant_categories_total Total categories per tenant",
        "# TYPE app_tenant_categories_total gauge",
        "# HELP app_tenant_brands_total Total brands per tenant",
        "# TYPE app_tenant_brands_total gauge",
        "# HELP app_tenant_owner_memberships_total Owner memberships per tenant",
        "# TYPE app_tenant_owner_memberships_total gauge",
        "# HELP app_tenant_staff_memberships_total Staff memberships per tenant",
        "# TYPE app_tenant_staff_memberships_total gauge",
        "# HELP app_tenant_has_bot_token Tenant bot token readiness flag",
        "# TYPE app_tenant_has_bot_token gauge",
        "# HELP app_tenant_has_admin_api_key Tenant admin api key readiness flag",
        "# TYPE app_tenant_has_admin_api_key gauge",
        "# HELP app_tenant_status_active Tenant active status flag",
        "# TYPE app_tenant_status_active gauge",
    ]

    async with async_session_maker() as session:
        tenants = list((await session.execute(select(Tenant).order_by(Tenant.id.asc()))).scalars().all())
        for tenant in tenants:
            slug = _escape_label(tenant.slug)
            title = _escape_label(tenant.title)
            labels = f'tenant_slug="{slug}",tenant_title="{title}"'
            products = await session.scalar(select(func.count(Product.id)).where(Product.tenant_id == tenant.id))
            categories = await session.scalar(select(func.count(Category.id)).where(Category.tenant_id == tenant.id))
            brands = await session.scalar(select(func.count(Brand.id)).where(Brand.tenant_id == tenant.id))
            owners = await session.scalar(
                select(func.count(TenantMembership.id)).where(
                    TenantMembership.tenant_id == tenant.id,
                    TenantMembership.role == UserRole.OWNER.value,
                )
            )
            staff = await session.scalar(
                select(func.count(TenantMembership.id)).where(
                    TenantMembership.tenant_id == tenant.id,
                    TenantMembership.role == UserRole.STAFF.value,
                )
            )
            lines.append(f"app_tenant_products_total{{{labels}}} {int(products or 0)}")
            lines.append(f"app_tenant_categories_total{{{labels}}} {int(categories or 0)}")
            lines.append(f"app_tenant_brands_total{{{labels}}} {int(brands or 0)}")
            lines.append(f"app_tenant_owner_memberships_total{{{labels}}} {int(owners or 0)}")
            lines.append(f"app_tenant_staff_memberships_total{{{labels}}} {int(staff or 0)}")
            lines.append(f"app_tenant_has_bot_token{{{labels}}} {1 if (tenant.bot_token or '').strip() else 0}")
            lines.append(f"app_tenant_has_admin_api_key{{{labels}}} {1 if (tenant.admin_api_key or '').strip() else 0}")
            lines.append(f"app_tenant_status_active{{{labels}}} {1 if tenant.status == 'active' else 0}")

    return "\n".join(lines) + "\n"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds trace_id + structured timing logs for every HTTP request."""

    async def dispatch(self, request: Request, call_next):
        # Принимаем внешний X-Request-ID (upstream proxy) или генерируем новый
        external_id = request.headers.get("X-Request-ID", "").strip()
        if external_id:
            set_trace_id(external_id)
            request_id = get_trace_id()
        else:
            request_id = new_trace_id()

        request.state.request_id = request_id
        metric_path = _normalize_metric_path(request)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "trace=%s method=%s path=%s status=500 duration_ms=%s",
                request_id, request.method, request.url.path, elapsed_ms,
            )
            raise

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        _observe_http_metrics(
            method=request.method,
            path=metric_path,
            status_code=response.status_code,
            duration_sec=(time.perf_counter() - started),
        )
        logger.info(
            "trace=%s method=%s path=%s status=%s duration_ms=%s",
            request_id, request.method, request.url.path,
            response.status_code, elapsed_ms,
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter backed by Redis."""

    def __init__(self, app, max_requests: int = 120, window_sec: int = 60) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
        return self._redis

    async def dispatch(self, request: Request, call_next):
        request_id = getattr(request.state, "request_id", "-")
        forwarded_for = request.headers.get("X-Forwarded-For")
        ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "unknown")
        key = f"rl:{ip}:{int(time.time()) // self.window_sec}"
        try:
            r = await self._get_redis()
            count = await r.incr(key)
            if count == 1:
                await r.expire(key, self.window_sec * 2)
            if count > self.max_requests:
                return JSONResponse({"detail": "Too many requests"}, status_code=429)
        except (RedisError, OSError, RuntimeError) as exc:
            logger.warning("rid=%s rate-limit-unavailable ip=%s: %s", request_id, ip, exc)
        return await call_next(request)


app = FastAPI(title="MLI Shop API")
BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
logger = logging.getLogger(__name__)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    max_requests=_RATE_LIMIT_MAX,
    window_sec=_RATE_LIMIT_WINDOW,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")

WEB_CHECKOUT_USER_TG_ID = 900000000001


def _build_fallback_tenant() -> Tenant:
    return Tenant(
        id=0,
        slug="default",
        title="Default Store",
        status="active",
        bot_token=settings.bot_token,
        domain=None,
        admin_api_key=os.getenv("WEB_ADMIN_KEY", "").strip() or None,
    )


async def _resolve_request_tenant(request: Request, tenant_slug: str | None = Query(default=None, alias="tenant")) -> Tenant:
    try:
        async with async_session_maker() as session:
            tenant = await resolve_tenant(
                session,
                slug=request.headers.get("X-Tenant-Slug") or tenant_slug,
                domain=request.headers.get("X-Tenant-Domain") or request.headers.get("X-Forwarded-Host") or request.headers.get("Host"),
            )
            await session.commit()
            return tenant
    except OperationalError:
        return _build_fallback_tenant()


async def _get_or_create_web_user(session, tenant: Tenant) -> User:
    stmt = select(User).where(User.tg_id == WEB_CHECKOUT_USER_TG_ID)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is not None and user.tenant_id != tenant.id:
        user.tenant_id = tenant.id
        await session.flush()
    if user is not None:
        await ensure_tenant_membership(session, user, tenant.id, UserRole.CLIENT.value)
    if user is not None:
        return user

    user = User(
        tg_id=WEB_CHECKOUT_USER_TG_ID,
        tenant_id=tenant.id,
        username="web_storefront",
        first_name="Web",
        last_name="Storefront",
        role=UserRole.CLIENT.value,
        ai_quota=0,
    )
    session.add(user)
    await session.flush()
    await ensure_tenant_membership(session, user, tenant.id, UserRole.CLIENT.value)
    return user


async def _get_tenant_settings(session, tenant_id: int) -> TenantSettings:
    return await get_or_create_tenant_settings(session, tenant_id)


def _serialize_tenant_settings(tenant: Tenant, settings_row: TenantSettings) -> AdminTenantSettingsResponse:
    return AdminTenantSettingsResponse(
        tenant_id=tenant.id,
        slug=tenant.slug,
        title=tenant.title,
        domain=tenant.domain,
        admin_api_key=tenant.admin_api_key,
        storefront_title=settings_row.storefront_title,
        support_label=settings_row.support_label,
        owner_title=settings_row.owner_title,
        staff_title=settings_row.staff_title,
        welcome_text_client=settings_row.welcome_text_client,
        welcome_text_staff=settings_row.welcome_text_staff,
        welcome_text_owner=settings_row.welcome_text_owner,
        button_labels={str(k): str(v) for k, v in (settings_row.button_labels or {}).items()},
        menu_client=[[str(item) for item in row] for row in (settings_row.menu_client or [])],
        menu_staff=[[str(item) for item in row] for row in (settings_row.menu_staff or [])],
        menu_owner=[[str(item) for item in row] for row in (settings_row.menu_owner or [])],
    )


def _serialize_tenant_row(tenant: Tenant, owner_tg_id: int | None = None) -> AdminTenantRow:
    return AdminTenantRow(
        tenant_id=tenant.id,
        slug=tenant.slug,
        title=tenant.title,
        domain=tenant.domain,
        status=tenant.status,
        owner_tg_id=owner_tg_id,
        has_bot_token=bool((tenant.bot_token or "").strip()),
        has_admin_api_key=bool((tenant.admin_api_key or "").strip()),
    )


def _serialize_tenant_preset_row(row: dict[str, object]) -> AdminTenantPresetRow:
    return AdminTenantPresetRow(
        key=str(row.get("key") or ""),
        title=str(row.get("title") or ""),
        description=str(row.get("description") or ""),
        category_names=[str(item) for item in list(row.get("category_names", []))],
        brand_names=[str(item) for item in list(row.get("brand_names", []))],
        demo_product_titles=[str(item.get("title") or "") for item in list(row.get("demo_products", []))],
    )


async def _create_tenant_from_payload(
    session,
    payload: AdminCreateTenantRequest | AdminBulkProvisionTenantItem,
) -> tuple[Tenant, int | None, int]:
    slug = (payload.slug or "").strip().lower()
    title = (payload.title or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug cannot be empty")
    if not title:
        raise HTTPException(status_code=400, detail="title cannot be empty")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}[a-z0-9]", slug):
        raise HTTPException(status_code=400, detail="slug must use lowercase latin letters, digits and hyphen")

    preset_key = (payload.preset_key or "").strip().lower() or None
    if preset_key and get_tenant_preset(preset_key) is None:
        raise HTTPException(status_code=400, detail="Unknown tenant preset")

    existing_slug = await session.scalar(select(Tenant.id).where(Tenant.slug == slug))
    if existing_slug is not None:
        raise HTTPException(status_code=409, detail="slug is already in use")

    domain = _extract_host(payload.domain)
    if domain:
        existing_domain = await session.scalar(select(Tenant.id).where(Tenant.domain == domain))
        if existing_domain is not None:
            raise HTTPException(status_code=409, detail="domain is already in use")

    tenant, _, _owner_user = await create_tenant_with_defaults(
        session,
        slug=slug,
        title=title,
        owner_tg_id=payload.owner_tg_id,
        domain=domain,
        bot_token=payload.bot_token,
        admin_api_key=payload.admin_api_key,
        owner_username=payload.owner_username,
        owner_first_name=payload.owner_first_name,
        owner_last_name=payload.owner_last_name,
    )
    demo_products_seeded = 0
    if preset_key:
        await apply_tenant_preset(session, tenant, preset_key, overwrite=False)
        demo_products_seeded = await seed_tenant_demo_products(session, tenant, preset_key)
    await session.flush()
    owner_tg_id = await get_primary_owner_tg_id(session, tenant.id)
    return tenant, owner_tg_id, demo_products_seeded


def _extract_bearer_token(authorization: str | None = Header(default=None, alias="Authorization")) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Use Authorization: Bearer <token>")
    return token.strip()


async def _require_admin_access(
    request: Request,
    token: str = Depends(_extract_bearer_token),
    tenant_slug: str | None = Query(default=None, alias="tenant"),
) -> Tenant:
    try:
        async with async_session_maker() as session:
            tenant = await resolve_tenant(
                session,
                slug=request.headers.get("X-Tenant-Slug") or tenant_slug,
                domain=request.headers.get("X-Tenant-Domain") or request.headers.get("X-Forwarded-Host") or request.headers.get("Host"),
            )
            await session.commit()
    except OperationalError:
        tenant = _build_fallback_tenant()

    admin_api_key = (tenant.admin_api_key or "").strip()
    if not admin_api_key or not secrets.compare_digest(token, admin_api_key):
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return tenant


async def _notify_order_to_telegram(
    order_id: int,
    full_name: str,
    phone: str,
    total_price: float,
    item_lines: list[str],
    tenant_id: int,
) -> None:
    bot_token = settings.bot_token
    try:
        admin_text = (
            f"🔔 <b>НОВЫЙ WEB-ЗАКАЗ #{order_id}</b>\n"
            f"👤 Клиент: {escape(full_name or '')}\n"
            f"📱 Телефон: {escape(phone or '')}\n"
            f"💰 Сумма: {total_price:.2f} ₽\n\n"
            f"📦 <b>Состав заказа:</b>\n"
            f"{''.join(item_lines)}"
        )
        async with async_session_maker() as session:
            tenant = await session.get(Tenant, tenant_id)
            if tenant and tenant.bot_token:
                bot_token = tenant.bot_token
            member_stmt = (
                select(User.tg_id, TenantMembership.role)
                .join(TenantMembership, TenantMembership.user_id == User.id)
                .where(
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.role.in_([UserRole.OWNER.value, UserRole.STAFF.value]),
                )
            )
            member_res = await session.execute(member_stmt)
            recipients = member_res.all()

        bot = Bot(token=bot_token)

        for staff_id, role in recipients:
            try:
                await bot.send_message(staff_id, admin_text, parse_mode="HTML")
            except (TelegramForbiddenError, TelegramNotFound, TelegramBadRequest, aiohttp.ClientError) as exc:
                logger.warning("Failed to send web order notification to %s %s: %s", role, staff_id, exc)
                continue
    finally:
        if 'bot' in locals():
            await bot.session.close()


def _map_product(product: Product) -> ProductResponse:
    media_items = sorted(product.photos, key=lambda item: item.id)
    primary_media = media_items[0] if media_items else None
    image_url = f"/api/products/{product.id}/image" if any((photo.media_type or "photo") == "photo" for photo in media_items) else None
    media = [
        ProductMediaResponse(
            id=item.id,
            media_type="video" if (item.media_type or "photo") == "video" else "photo",
            url=f"/api/products/{product.id}/media/{item.id}",
            is_primary=bool(primary_media and primary_media.id == item.id),
        )
        for item in media_items
    ]
    return ProductResponse(
        id=product.id,
        name=product.title,
        description=product.description,
        price=float(product.sale_price),
        category_id=product.category_id,
        category_name=product.category.name if product.category else None,
        brand_id=product.brand_id,
        brand_name=product.brand.name if product.brand else None,
        stock=sum(item.quantity for item in product.stock),
        image_url=image_url,
        primary_media_url=(f"/api/products/{product.id}/media/{primary_media.id}" if primary_media else None),
        primary_media_type=((primary_media.media_type or "photo") if primary_media else None),
        media=media,
    )


async def _download_telegram_file(bot_token: str, file_id: str) -> tuple[bytes, str]:
    get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as http:
        async with http.get(get_file_url, params={"file_id": file_id}) as tg_resp:
            if tg_resp.status != 200:
                raise HTTPException(status_code=502, detail="Failed to load media metadata")
            payload = await tg_resp.json()
            if not payload.get("ok"):
                raise HTTPException(status_code=502, detail="Invalid media metadata response")
            file_path = payload.get("result", {}).get("file_path")
            if not file_path:
                raise HTTPException(status_code=404, detail="Media path not found")

        file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        async with http.get(file_url) as file_resp:
            if file_resp.status != 200:
                raise HTTPException(status_code=502, detail="Failed to download product media")
            content_type = file_resp.headers.get("Content-Type", "application/octet-stream")
            content = await file_resp.read()
    return content, content_type


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/product/{product_id}")
async def product_page(product_id: int) -> FileResponse:
    _ = product_id
    return FileResponse(WEB_DIR / "product.html")


@app.get("/cart")
async def cart_page() -> FileResponse:
    return FileResponse(WEB_DIR / "cart.html")


@app.get("/ai-chat")
async def ai_chat_page() -> FileResponse:
    return FileResponse(WEB_DIR / "ai_chat.html")


@app.get("/about")
async def about_page() -> FileResponse:
    return FileResponse(WEB_DIR / "about.html")


@app.get("/admin")
async def admin_page() -> FileResponse:
    return FileResponse(WEB_DIR / "admin.html")


@app.get("/api/ping")
async def ping() -> dict[str, str]:
    _ = settings.db_url
    return {"status": "ok", "message": "API is running"}


@app.get("/api/health")
async def health() -> dict[str, str | int]:
    async with async_session_maker() as session:
        tenant = await ensure_default_tenant(session)
        await session.execute(text("SELECT 1"))
        total_products = await session.scalar(select(func.count(Product.id)).where(Product.tenant_id == tenant.id))
    return {
        "status": "ok",
        "database": "connected",
        "products": int(total_products or 0),
    }


@app.get("/api/health/tenant", response_model=TenantSmokeResponse)
async def tenant_health_smoke(tenant: Tenant = Depends(_resolve_request_tenant)) -> TenantSmokeResponse:
    async with async_session_maker() as session:
        db_tenant = await session.get(Tenant, tenant.id)
        if db_tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        await session.execute(text("SELECT 1"))
        categories = await session.scalar(select(func.count(Category.id)).where(Category.tenant_id == db_tenant.id))
        brands = await session.scalar(select(func.count(Brand.id)).where(Brand.tenant_id == db_tenant.id))
        products = await session.scalar(select(func.count(Product.id)).where(Product.tenant_id == db_tenant.id))
        owner_memberships = await session.scalar(
            select(func.count(TenantMembership.id)).where(
                TenantMembership.tenant_id == db_tenant.id,
                TenantMembership.role == UserRole.OWNER.value,
            )
        )
        staff_memberships = await session.scalar(
            select(func.count(TenantMembership.id)).where(
                TenantMembership.tenant_id == db_tenant.id,
                TenantMembership.role == UserRole.STAFF.value,
            )
        )
    return TenantSmokeResponse(
        status="ok",
        tenant_id=db_tenant.id,
        tenant_slug=db_tenant.slug,
        tenant_title=db_tenant.title,
        tenant_status=db_tenant.status,
        domain=db_tenant.domain,
        has_bot_token=bool((db_tenant.bot_token or "").strip()),
        has_admin_api_key=bool((db_tenant.admin_api_key or "").strip()),
        categories=int(categories or 0),
        brands=int(brands or 0),
        products=int(products or 0),
        owner_memberships=int(owner_memberships or 0),
        staff_memberships=int(staff_memberships or 0),
    )


@app.get("/api/metrics")
async def metrics() -> Response:
    payload = _render_prometheus_metrics()
    return Response(content=payload, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/api/metrics/tenants")
async def tenant_metrics() -> Response:
    payload = await _render_tenant_prometheus_metrics()
    return Response(content=payload, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/api/products", response_model=list[ProductResponse])
async def get_products(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    category_id: int | None = Query(default=None, ge=1),
    tenant: Tenant = Depends(_resolve_request_tenant),
) -> list[ProductResponse]:
    async with async_session_maker() as session:
        stmt = select(Product).options(
            selectinload(Product.stock),
            selectinload(Product.photos),
            selectinload(Product.category),
            selectinload(Product.brand),
        ).where(Product.tenant_id == tenant.id)
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        stmt = stmt.order_by(Product.id).offset(offset).limit(limit)
        result = await session.execute(stmt)
        products = result.scalars().all()
        return [_map_product(product) for product in products]


@app.get("/api/products/{product_id}", response_model=ProductResponse)
async def get_product_by_id(product_id: int, tenant: Tenant = Depends(_resolve_request_tenant)) -> ProductResponse:
    async with async_session_maker() as session:
        stmt = select(Product).options(
            selectinload(Product.stock),
            selectinload(Product.photos),
            selectinload(Product.category),
            selectinload(Product.brand),
        ).where(Product.id == product_id, Product.tenant_id == tenant.id)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return _map_product(product)


@app.get("/api/products/{product_id}/image")
async def get_product_image(product_id: int, tenant: Tenant = Depends(_resolve_request_tenant)) -> Response:
    async with async_session_maker() as session:
        stmt = select(Product).options(selectinload(Product.photos)).where(Product.id == product_id, Product.tenant_id == tenant.id)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        if not product.photos:
            raise HTTPException(status_code=404, detail="Product image not found")

        image = next((photo for photo in product.photos if (photo.media_type or "photo") == "photo"), None)
        if image is None:
            raise HTTPException(status_code=404, detail="Product image not found")

        file_id = image.file_id

    bot_token = tenant.bot_token or settings.bot_token
    content, content_type = await _download_telegram_file(bot_token, file_id)

    return Response(content=content, media_type=content_type)


@app.get("/api/products/{product_id}/media/{media_id}")
async def get_product_media(product_id: int, media_id: int, tenant: Tenant = Depends(_resolve_request_tenant)) -> Response:
    async with async_session_maker() as session:
        stmt = select(Product).options(selectinload(Product.photos)).where(Product.id == product_id, Product.tenant_id == tenant.id)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")

        media = next((item for item in product.photos if item.id == media_id), None)
        if media is None:
            raise HTTPException(status_code=404, detail="Product media not found")

    bot_token = tenant.bot_token or settings.bot_token
    content, content_type = await _download_telegram_file(bot_token, media.file_id)
    return Response(content=content, media_type=content_type)


@app.post("/api/orders", response_model=WebOrderResponse)
async def create_web_order(payload: WebOrderRequest, tenant: Tenant = Depends(_resolve_request_tenant)) -> WebOrderResponse:
    if not payload.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    digits = re.sub(r"\D", "", payload.phone)
    if len(digits) < 7:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    async with async_session_maker() as session:
        user = await _get_or_create_web_user(session, tenant)
        cart_items_for_order: list[CartItem] = []
        item_lines: list[str] = []

        for item in payload.items:
            quantity = max(1, int(item.quantity or 1))

            stmt = select(Product).options(
                selectinload(Product.stock),
                selectinload(Product.brand),
            ).where(Product.id == item.product_id, Product.tenant_id == tenant.id)
            res = await session.execute(stmt)
            product = res.scalar_one_or_none()
            if product is None:
                raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")

            selected_size = (item.size or "").strip()
            if not selected_size:
                best_stock = max(product.stock, key=lambda stock: stock.quantity, default=None)
                if best_stock is None or best_stock.quantity < quantity:
                    raise HTTPException(status_code=409, detail=f"Product {product.id} is out of stock")
                selected_size = best_stock.size

            stock_stmt = select(func.sum(ProductStock.quantity)).where(
                ProductStock.product_id == product.id,
                ProductStock.size == selected_size,
            )
            stock_res = await session.execute(stock_stmt)
            available = int(stock_res.scalar_one() or 0)
            if available < quantity:
                raise HTTPException(
                    status_code=409,
                    detail=f"Insufficient stock for product {product.id}, size {selected_size}",
                )

            cart_item = CartItem(
                user=user,
                product=product,
                size=selected_size,
                quantity=quantity,
                price_at_add=Decimal(str(product.sale_price)),
            )
            cart_items_for_order.append(cart_item)

            brand_name = product.brand.name if product.brand else ""
            sku_part = f" [{product.sku}]" if product.sku else ""
            item_lines.append(f"— {brand_name} {product.title}{sku_part} ({selected_size}) x{quantity}\n")

        orders_repo = OrdersRepo(session, tenant_id=tenant.id)
        order = await orders_repo.create_order(
            user=user,
            full_name=payload.full_name.strip() or "Клиент сайта",
            phone=payload.phone.strip(),
            address=(payload.address or "Не указан (оформлено через сайт)").strip(),
            cart_items=cart_items_for_order,
        )

        if order is None:
            raise HTTPException(status_code=409, detail="Order creation failed due to stock changes")

        await session.commit()
        total_price = float(order.total_price)

    await _notify_order_to_telegram(
        order_id=order.id,
        full_name=payload.full_name.strip() or "Клиент сайта",
        phone=payload.phone.strip(),
        total_price=total_price,
        item_lines=item_lines,
        tenant_id=tenant.id,
    )

    return WebOrderResponse(
        status="ok",
        order_id=order.id,
        total_price=total_price,
        message="Order created successfully",
    )


@app.get("/api/admin/meta", response_model=AdminMetaResponse)
async def get_admin_meta(tenant: Tenant = Depends(_require_admin_access)) -> AdminMetaResponse:
    async with async_session_maker() as session:
        repo = CatalogRepo(session, tenant_id=tenant.id)
        categories = await repo.list_categories()
        brands = await repo.list_brands()

    return AdminMetaResponse(
        categories=[{"id": category.id, "name": category.name} for category in categories],
        brands=[{"id": brand.id, "name": brand.name} for brand in brands],
    )


@app.post("/api/admin/products", response_model=AdminCreateProductResponse)
async def create_product_from_admin(
    payload: AdminCreateProductRequest,
    tenant: Tenant = Depends(_require_admin_access),
) -> AdminCreateProductResponse:
    title = (payload.title or "").strip()
    category_name = (payload.category_name or "").strip()
    brand_name = (payload.brand_name or "").strip()
    size = (payload.size or "").strip()

    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    if not category_name:
        raise HTTPException(status_code=400, detail="Category is required")
    if not brand_name:
        raise HTTPException(status_code=400, detail="Brand is required")
    if not size:
        raise HTTPException(status_code=400, detail="Size is required")
    if payload.quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity must be >= 0")
    if payload.purchase_price < 0 or payload.sale_price < 0:
        raise HTTPException(status_code=400, detail="Prices must be >= 0")

    async with async_session_maker() as session:
        repo = CatalogRepo(session, tenant_id=tenant.id)
        category = await repo.get_or_create_category(category_name)
        brand = await repo.get_or_create_brand(brand_name)
        product = await repo.create_product(
            title=title,
            description=(payload.description or "").strip() or None,
            purchase_price=float(payload.purchase_price),
            sale_price=float(payload.sale_price),
            category=category,
            brand=brand,
        )

        if payload.photo_file_id:
            await repo.add_photo(product=product, file_id=payload.photo_file_id.strip())

        if payload.quantity > 0:
            await repo.add_stock(product=product, size=size, quantity=int(payload.quantity))

        await session.commit()

    return AdminCreateProductResponse(
        status="ok",
        product_id=product.id,
        sku=product.sku,
        message="Product created",
    )


@app.get("/api/admin/products", response_model=AdminProductsResponse)
async def list_admin_products(
    tenant: Tenant = Depends(_require_admin_access),
    limit: int = Query(default=50, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
) -> AdminProductsResponse:
    async with async_session_maker() as session:
        total_stmt = select(func.count(Product.id)).where(Product.tenant_id == tenant.id)
        total = int(await session.scalar(total_stmt) or 0)

        stmt = (
            select(Product)
            .options(
                selectinload(Product.stock),
                selectinload(Product.category),
                selectinload(Product.brand),
            )
            .where(Product.tenant_id == tenant.id)
            .order_by(Product.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        products = result.scalars().all()

    items = [
        AdminProductRow(
            id=product.id,
            sku=product.sku,
            title=product.title,
            description=product.description,
            category_name=product.category.name if product.category else "",
            brand_name=product.brand.name if product.brand else "",
            purchase_price=float(product.purchase_price),
            sale_price=float(product.sale_price),
            total_stock=sum(stock.quantity for stock in product.stock),
        )
        for product in products
    ]
    return AdminProductsResponse(items=items, total=total)


@app.patch("/api/admin/products/{product_id}", response_model=AdminCreateProductResponse)
async def update_admin_product(
    product_id: int,
    payload: AdminUpdateProductRequest,
    tenant: Tenant = Depends(_require_admin_access),
) -> AdminCreateProductResponse:
    async with async_session_maker() as session:
        repo = CatalogRepo(session, tenant_id=tenant.id)
        stmt = (
            select(Product)
            .options(
                selectinload(Product.stock),
                selectinload(Product.category),
                selectinload(Product.brand),
            )
            .where(Product.id == product_id, Product.tenant_id == tenant.id)
        )
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")

        if payload.title is not None:
            new_title = payload.title.strip()
            if not new_title:
                raise HTTPException(status_code=400, detail="Title cannot be empty")
            product.title = new_title

        if payload.description is not None:
            product.description = payload.description.strip() or None

        if payload.purchase_price is not None:
            if payload.purchase_price < 0:
                raise HTTPException(status_code=400, detail="purchase_price must be >= 0")
            product.purchase_price = payload.purchase_price

        if payload.sale_price is not None:
            if payload.sale_price < 0:
                raise HTTPException(status_code=400, detail="sale_price must be >= 0")
            product.sale_price = payload.sale_price

        if payload.category_name is not None:
            category_name = payload.category_name.strip()
            if not category_name:
                raise HTTPException(status_code=400, detail="category_name cannot be empty")
            category = await repo.get_or_create_category(category_name)
            product.category = category

        if payload.brand_name is not None:
            brand_name = payload.brand_name.strip()
            if not brand_name:
                raise HTTPException(status_code=400, detail="brand_name cannot be empty")
            brand = await repo.get_or_create_brand(brand_name)
            product.brand = brand

        if payload.quantity is not None:
            if payload.quantity < 0:
                raise HTTPException(status_code=400, detail="quantity must be >= 0")
            if not payload.size or not payload.size.strip():
                raise HTTPException(status_code=400, detail="size is required when quantity is provided")
            await repo.update_stock_quantity(product.id, payload.size.strip(), int(payload.quantity))

        await session.commit()

    return AdminCreateProductResponse(
        status="ok",
        product_id=product_id,
        sku=product.sku,
        message="Product updated",
    )


@app.delete("/api/admin/products/{product_id}", response_model=AdminDeleteProductResponse)
async def delete_admin_product(
    product_id: int,
    tenant: Tenant = Depends(_require_admin_access),
) -> AdminDeleteProductResponse:
    async with async_session_maker() as session:
        repo = CatalogRepo(session, tenant_id=tenant.id)
        deleted = await repo.delete_product(product_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Product not found")
        await session.commit()

    return AdminDeleteProductResponse(status="ok", product_id=product_id, message="Product deleted")


@app.get("/api/admin/tenant-settings", response_model=AdminTenantSettingsResponse)
async def get_admin_tenant_settings(tenant: Tenant = Depends(_require_admin_access)) -> AdminTenantSettingsResponse:
    async with async_session_maker() as session:
        db_tenant = await session.get(Tenant, tenant.id) if tenant.id else tenant
        settings_row = await _get_tenant_settings(session, tenant.id)
        return _serialize_tenant_settings(db_tenant or tenant, settings_row)


@app.put("/api/admin/tenant-settings", response_model=AdminTenantSettingsResponse)
async def update_admin_tenant_settings(
    payload: AdminTenantSettingsUpdateRequest,
    tenant: Tenant = Depends(_require_admin_access),
) -> AdminTenantSettingsResponse:
    async with async_session_maker() as session:
        db_tenant = await session.get(Tenant, tenant.id)
        if db_tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        settings_row = await _get_tenant_settings(session, tenant.id)

        if payload.slug is not None:
            new_slug = (payload.slug or "").strip().lower()
            if not new_slug:
                raise HTTPException(status_code=400, detail="slug cannot be empty")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}[a-z0-9]", new_slug):
                raise HTTPException(status_code=400, detail="slug must use lowercase latin letters, digits and hyphen")
            existing_slug_stmt = select(Tenant.id).where(Tenant.slug == new_slug, Tenant.id != db_tenant.id)
            existing_slug = await session.scalar(existing_slug_stmt)
            if existing_slug is not None:
                raise HTTPException(status_code=409, detail="slug is already in use")
            db_tenant.slug = new_slug

        if payload.title is not None:
            db_tenant.title = payload.title.strip() or db_tenant.title
        if payload.domain is not None:
            normalized_domain = _extract_host(payload.domain)
            if normalized_domain:
                existing_domain_stmt = select(Tenant.id).where(Tenant.domain == normalized_domain, Tenant.id != db_tenant.id)
                existing_domain = await session.scalar(existing_domain_stmt)
                if existing_domain is not None:
                    raise HTTPException(status_code=409, detail="domain is already in use")
            db_tenant.domain = normalized_domain or None
        if payload.admin_api_key is not None:
            db_tenant.admin_api_key = (payload.admin_api_key or "").strip() or None
        if payload.storefront_title is not None:
            settings_row.storefront_title = payload.storefront_title.strip() or settings_row.storefront_title
        if payload.support_label is not None:
            settings_row.support_label = payload.support_label.strip() or settings_row.support_label
        if payload.owner_title is not None:
            settings_row.owner_title = payload.owner_title.strip() or settings_row.owner_title
        if payload.staff_title is not None:
            settings_row.staff_title = payload.staff_title.strip() or settings_row.staff_title
        if payload.welcome_text_client is not None:
            settings_row.welcome_text_client = payload.welcome_text_client.strip() or None
        if payload.welcome_text_staff is not None:
            settings_row.welcome_text_staff = payload.welcome_text_staff.strip() or None
        if payload.welcome_text_owner is not None:
            settings_row.welcome_text_owner = payload.welcome_text_owner.strip() or None
        if payload.button_labels is not None:
            settings_row.button_labels = {str(k): str(v) for k, v in payload.button_labels.items()}
        if payload.menu_client is not None:
            settings_row.menu_client = [[str(item) for item in row] for row in payload.menu_client]
        if payload.menu_staff is not None:
            settings_row.menu_staff = [[str(item) for item in row] for row in payload.menu_staff]
        if payload.menu_owner is not None:
            settings_row.menu_owner = [[str(item) for item in row] for row in payload.menu_owner]

        await session.commit()
        await session.refresh(db_tenant)
        await session.refresh(settings_row)
        return _serialize_tenant_settings(db_tenant, settings_row)


@app.post("/api/admin/tenant-settings/regenerate-key", response_model=AdminTenantSettingsResponse)
async def regenerate_admin_tenant_api_key(tenant: Tenant = Depends(_require_admin_access)) -> AdminTenantSettingsResponse:
    async with async_session_maker() as session:
        db_tenant = await session.get(Tenant, tenant.id)
        if db_tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        settings_row = await _get_tenant_settings(session, tenant.id)
        db_tenant.admin_api_key = secrets.token_urlsafe(24)
        await session.commit()
        await session.refresh(db_tenant)
        return _serialize_tenant_settings(db_tenant, settings_row)


@app.delete("/api/admin/tenant-settings", response_model=AdminTenantSettingsResponse)
async def reset_admin_tenant_settings(tenant: Tenant = Depends(_require_admin_access)) -> AdminTenantSettingsResponse:
    async with async_session_maker() as session:
        db_tenant = await session.get(Tenant, tenant.id) if tenant.id else tenant
        await session.delete((await _get_tenant_settings(session, tenant.id)))
        await session.flush()
        settings_row = await _get_tenant_settings(session, tenant.id)
        await session.commit()
        return _serialize_tenant_settings(db_tenant or tenant, settings_row)


@app.get("/api/admin/tenants", response_model=AdminTenantsResponse)
async def list_admin_tenants(_: Tenant = Depends(_require_admin_access)) -> AdminTenantsResponse:
    async with async_session_maker() as session:
        stmt = select(Tenant).order_by(Tenant.id.asc())
        tenants = list((await session.execute(stmt)).scalars().all())
        items: list[AdminTenantRow] = []
        for tenant in tenants:
            owner_tg_id = await get_primary_owner_tg_id(session, tenant.id)
            items.append(_serialize_tenant_row(tenant, owner_tg_id))
        return AdminTenantsResponse(items=items, total=len(items))


@app.get("/api/admin/tenant-presets", response_model=AdminTenantPresetsResponse)
async def list_admin_tenant_presets(_: Tenant = Depends(_require_admin_access)) -> AdminTenantPresetsResponse:
    items = [_serialize_tenant_preset_row(item) for item in list_tenant_presets()]
    return AdminTenantPresetsResponse(items=items, total=len(items))


@app.post("/api/admin/tenants", response_model=AdminCreateTenantResponse, status_code=201)
async def create_admin_tenant(
    payload: AdminCreateTenantRequest,
    _: Tenant = Depends(_require_admin_access),
) -> AdminCreateTenantResponse:
    async with async_session_maker() as session:
        tenant, owner_tg_id, demo_products_seeded = await _create_tenant_from_payload(session, payload)
        await session.commit()
        return AdminCreateTenantResponse(
            status="ok",
            tenant=_serialize_tenant_row(tenant, owner_tg_id),
            admin_api_key=tenant.admin_api_key,
            demo_products_seeded=demo_products_seeded,
            message="Tenant created",
        )


@app.post("/api/admin/tenants/bulk-provision", response_model=AdminBulkProvisionTenantsResponse, status_code=201)
async def bulk_provision_admin_tenants(
    payload: AdminBulkProvisionTenantsRequest,
    _: Tenant = Depends(_require_admin_access),
) -> AdminBulkProvisionTenantsResponse:
    if not payload.items:
        raise HTTPException(status_code=400, detail="items cannot be empty")

    seen_slugs: set[str] = set()
    for item in payload.items:
        slug = (item.slug or "").strip().lower()
        if slug in seen_slugs:
            raise HTTPException(status_code=400, detail="Duplicate slug in bulk payload")
        seen_slugs.add(slug)

    created: list[AdminBulkProvisionResultRow] = []
    async with async_session_maker() as session:
        for item in payload.items:
            tenant, owner_tg_id, demo_products_seeded = await _create_tenant_from_payload(session, item)
            created.append(
                AdminBulkProvisionResultRow(
                    preset_key=(item.preset_key or "").strip().lower() or None,
                    tenant=_serialize_tenant_row(tenant, owner_tg_id),
                    admin_api_key=tenant.admin_api_key,
                    demo_products_seeded=demo_products_seeded,
                )
            )
        await session.commit()

    return AdminBulkProvisionTenantsResponse(
        status="ok",
        created=created,
        total_created=len(created),
        message="Bulk tenant provisioning completed",
    )


@app.get("/api/admin/reports/period.xlsx")
async def export_period_report_xlsx(
    _: None = Depends(_require_admin_access),
    date_from: str = Query(..., min_length=10, max_length=10),
    date_to: str = Query(..., min_length=10, max_length=10),
) -> Response:
    try:
        start_dt = datetime.strptime(date_from, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
    except ValueError:
        raise HTTPException(status_code=400, detail="Use date format YYYY-MM-DD")

    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="date_from must be less than or equal to date_to")

    async with async_session_maker() as session:
        content = await build_erp_report_xlsx(session, start_dt, end_dt)

    filename = f"erp_report_{date_from}_{date_to}.xlsx"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


async def _request_ai_web(messages_payload: list[dict[str, str]]) -> str:
    provider = (settings.ai_provider or "groq").lower().strip()
    providers = {
        "groq": {
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "api_key": settings.groq_api_key,
            "model": settings.groq_model or "llama-3.3-70b-versatile",
        },
        "deepseek": {
            "url": "https://api.deepseek.com/v1/chat/completions",
            "api_key": settings.deepseek_api_key,
            "model": settings.deepseek_model or "deepseek-chat",
        },
    }
    if provider not in providers:
        provider = "groq"

    cfg = providers[provider]
    api_key = cfg["api_key"]
    if not api_key:
        raise HTTPException(status_code=503, detail=f"{provider} API key is missing")

    payload = {
        "model": (settings.ai_model or cfg["model"]),
        "messages": messages_payload,
        "temperature": 0.5,
        "max_tokens": 800,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=max(5, settings.ai_request_timeout_sec))
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.post(cfg["url"], json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise HTTPException(status_code=502, detail=f"AI API error {resp.status}: {body[:300]}")
            data = await resp.json()

    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.error("AI response parsing failed: %s", exc)
        raise HTTPException(status_code=502, detail="Invalid AI response format")


async def _build_catalog_context_for_ai(user_message: str, tenant_id: int) -> str:
    query = (user_message or "").strip()
    query_tokens = [token for token in re.findall(r"[\w-]+", query.lower()) if len(token) > 2]

    async with async_session_maker() as session:
        stmt = (
            select(Product)
            .options(
                selectinload(Product.stock),
                selectinload(Product.category),
                selectinload(Product.brand),
            )
            .where(Product.tenant_id == tenant_id)
        )

        if query_tokens:
            search_clauses = []
            for token in query_tokens[:6]:
                pattern = f"%{token}%"
                search_clauses.append(Product.title.ilike(pattern))
                search_clauses.append(Product.description.ilike(pattern))
            stmt = stmt.where(or_(*search_clauses))

        stmt = stmt.order_by(Product.id.desc()).limit(20)
        result = await session.execute(stmt)
        products = result.scalars().all()

        if not products:
            fallback_stmt = (
                select(Product)
                .options(
                    selectinload(Product.stock),
                    selectinload(Product.category),
                    selectinload(Product.brand),
                )
                .where(Product.tenant_id == tenant_id)
                .order_by(Product.id.desc())
                .limit(8)
            )
            fallback_res = await session.execute(fallback_stmt)
            products = fallback_res.scalars().all()

    if not products:
        return "Каталог сейчас пуст."

    lines: list[str] = []
    for product in products:
        total_stock = sum(item.quantity for item in product.stock)
        category_name = product.category.name if product.category else "Без категории"
        brand_name = product.brand.name if product.brand else "Без бренда"
        lines.append(
            f"- ID {product.id}: {product.title} | {brand_name} | {category_name} | "
            f"цена {float(product.sale_price):.2f} ₽ | остаток {total_stock}"
        )

    return "\n".join(lines)


@app.post("/api/ai/chat", response_model=WebAIChatResponse)
async def web_ai_chat(payload: WebAIChatRequest, tenant: Tenant = Depends(_resolve_request_tenant)) -> WebAIChatResponse:
    user_message = (payload.message or "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Message is empty")

    safe_user_message = escape(user_message)
    catalog_context = await _build_catalog_context_for_ai(user_message, tenant.id)
    history = payload.history[-20:] if payload.history else []
    messages_payload: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                f"Ты AI-консультант магазина {tenant.title}. Отвечай кратко, по делу и помогай выбрать товар. "
                "Используй только актуальные данные каталога ниже, не выдумывай наличие и цену.\n\n"
                f"Контекст каталога:\n{catalog_context}"
            ),
        }
    ]
    for item in history:
        role = str(item.get("role", "user"))
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content", "")).strip()
        if content:
            messages_payload.append({"role": role, "content": content})

    messages_payload.append({"role": "user", "content": safe_user_message})
    answer = await _request_ai_web(messages_payload)
    return WebAIChatResponse(status="ok", answer=answer)


if __name__ == "__main__":
    port = int(os.getenv("WEB_API_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)