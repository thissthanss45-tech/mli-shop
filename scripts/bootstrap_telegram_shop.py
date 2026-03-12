from __future__ import annotations

import argparse
import asyncio
import sys
import secrets
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from database.db_manager import async_session_maker
from models import Tenant, User, UserRole
from utils.tenants import (
    _extract_host,
    apply_tenant_preset,
    create_tenant_with_defaults,
    ensure_tenant_membership,
    get_primary_owner_tg_id,
    resolve_tenant_by_slug,
    seed_tenant_demo_products,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a Telegram shop tenant")
    parser.add_argument("--slug", required=True, help="Tenant slug, e.g. flowers-boutique")
    parser.add_argument("--title", required=True, help="Store title")
    parser.add_argument("--preset", default="flowers", help="Tenant preset key")
    parser.add_argument("--bot-token", required=True, help="Telegram bot token for the active shop")
    parser.add_argument("--owner-id", required=True, type=int, help="Telegram user id of the owner")
    parser.add_argument("--domain", default="", help="Optional domain name")
    parser.add_argument("--tenant-admin-key", default="", help="Optional tenant-specific admin API key")
    parser.add_argument("--owner-username", default="")
    parser.add_argument("--owner-first-name", default="")
    parser.add_argument("--owner-last-name", default="")
    parser.add_argument(
        "--replace-owner",
        action="store_true",
        help="Demote other owner memberships in the tenant and make the provided owner the primary one",
    )
    return parser.parse_args()


async def _bootstrap(args: argparse.Namespace) -> None:
    async with async_session_maker() as session:
        normalized_slug = args.slug.strip().lower()
        normalized_title = args.title.strip()
        normalized_domain = _extract_host(args.domain)
        normalized_bot_token = args.bot_token.strip()
        tenant_admin_key = args.tenant_admin_key.strip()

        duplicate_bot_token_stmt = select(Tenant).where(Tenant.bot_token == normalized_bot_token, Tenant.slug != normalized_slug)
        duplicate_bot_token_owner = await session.scalar(duplicate_bot_token_stmt)
        if duplicate_bot_token_owner is not None:
            raise RuntimeError(
                f"BOT_TOKEN already assigned to tenant '{duplicate_bot_token_owner.slug}'. "
                "Use a dedicated token per shop or reuse that tenant."
            )

        duplicate_domain_stmt = select(Tenant).where(Tenant.domain == normalized_domain, Tenant.slug != normalized_slug)
        duplicate_domain_owner = await session.scalar(duplicate_domain_stmt) if normalized_domain else None
        if duplicate_domain_owner is not None:
            raise RuntimeError(f"Domain '{normalized_domain}' already assigned to tenant '{duplicate_domain_owner.slug}'.")

        tenant = await resolve_tenant_by_slug(session, normalized_slug)
        demo_products_seeded = 0
        if tenant is None:
            effective_admin_key = tenant_admin_key or secrets.token_urlsafe(24)
            tenant, _settings, _owner = await create_tenant_with_defaults(
                session,
                slug=normalized_slug,
                title=normalized_title,
                domain=normalized_domain,
                bot_token=normalized_bot_token,
                admin_api_key=effective_admin_key,
                owner_tg_id=args.owner_id,
                owner_username=args.owner_username,
                owner_first_name=args.owner_first_name,
                owner_last_name=args.owner_last_name,
            )
        else:
            tenant.title = normalized_title or tenant.title
            tenant.status = "active"
            tenant.domain = normalized_domain or None
            tenant.bot_token = normalized_bot_token
            if tenant_admin_key:
                tenant.admin_api_key = tenant_admin_key

            owner_stmt = select(User).where(User.tg_id == args.owner_id)
            owner = await session.scalar(owner_stmt)
            if owner is None:
                owner = User(
                    tg_id=args.owner_id,
                    tenant_id=tenant.id,
                    username=args.owner_username.strip() or None,
                    first_name=args.owner_first_name.strip() or None,
                    last_name=args.owner_last_name.strip() or None,
                    role=UserRole.OWNER.value,
                    ai_quota=0,
                )
                session.add(owner)
                await session.flush()
            elif owner.tenant_id is None:
                owner.tenant_id = tenant.id

            membership = await ensure_tenant_membership(session, owner, tenant.id, UserRole.OWNER.value)
            membership.role = UserRole.OWNER.value
            owner.role = UserRole.OWNER.value

            if args.replace_owner:
                owners_stmt = (
                    select(TenantMembership, User)
                    .join(User, User.id == TenantMembership.user_id)
                    .where(TenantMembership.tenant_id == tenant.id, TenantMembership.role == UserRole.OWNER.value)
                )
                owners_res = await session.execute(owners_stmt)
                for existing_membership, existing_owner in owners_res.all():
                    if existing_owner.tg_id == args.owner_id:
                        continue
                    existing_membership.role = UserRole.CLIENT.value
                    existing_owner.role = UserRole.CLIENT.value

        await apply_tenant_preset(session, tenant, args.preset, overwrite=False)
        demo_products_seeded = await seed_tenant_demo_products(session, tenant, args.preset)
        await session.commit()
        owner_tg_id = await get_primary_owner_tg_id(session, tenant.id)
        effective_admin_key = tenant.admin_api_key

    print("Telegram shop bootstrap complete")
    print(f"tenant_slug={normalized_slug}")
    print(f"tenant_title={normalized_title}")
    print(f"owner_tg_id={owner_tg_id}")
    print(f"tenant_admin_api_key={effective_admin_key}")
    print(f"demo_products_seeded={demo_products_seeded}")


def main() -> None:
    args = parse_args()
    asyncio.run(_bootstrap(args))


if __name__ == "__main__":
    main()