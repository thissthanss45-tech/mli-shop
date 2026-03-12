# Multi-Tenant SaaS Smoke Checklist

Цель: быстрый ручной smoke-check ключевых multi-tenant сценариев после изменений в tenant routing, auth и bot runtime.

## 1. Tenant Identity

- [ ] Открыть `/admin` и ввести действующий admin key текущего tenant.
- [ ] Нажать `Загрузить настройки` и убедиться, что загружаются корректные `slug`, `domain`, `title` и tenant-specific кнопки.
- [ ] Изменить `slug`, сохранить настройки и убедиться, что повторная загрузка через `?tenant=<new-slug>` проходит успешно.
- [ ] Проверить, что старый `slug` больше не используется для admin API доступа.

## 2. Domain Routing

- [ ] Назначить tenant новый `domain` в админке и сохранить изменения.
- [ ] Выполнить запрос к storefront API с нужным `Host` или `X-Tenant-Domain` и убедиться, что возвращаются товары именно этого tenant.
- [ ] Проверить `GET /api/products` и `GET /api/products/{id}` для tenant domain context.
- [ ] Проверить `POST /api/orders` в том же domain context и убедиться, что заказ создаётся внутри правильного tenant.

## 3. Admin Key Rotation

- [ ] Нажать `Сгенерировать новый admin API key` в админке.
- [ ] Убедиться, что новый ключ подставился в поля формы.
- [ ] Проверить, что новый ключ даёт доступ к `GET /api/admin/tenant-settings`.
- [ ] Проверить, что старый ключ больше не проходит в admin API.

## 4. Storefront Isolation

- [ ] Для tenant A загрузить каталог и убедиться, что не видны товары tenant B.
- [ ] Для tenant B выполнить тот же запрос и проверить обратную изоляцию.
- [ ] Проверить, что категории/бренды в `/api/admin/meta` соответствуют только текущему tenant.

## 5. Bot Runtime By Token

- [ ] Запустить бота с tenant-specific `BOT_TOKEN`.
- [ ] Отправить `/start` и убедиться, что меню и приветствие берутся из `tenant_settings` именно этого tenant.
- [ ] Для owner/staff/client проверить, что показываются их tenant-specific меню.
- [ ] Убедиться, что worker пишет `AIChatLog.tenant_id` в tenant, разрешённый через bot token.

## 6. Order And Notification Flow

- [ ] Создать заказ через web storefront tenant A.
- [ ] Убедиться, что уведомление уходит только owner/staff этого tenant.
- [ ] Проверить, что заказ не появляется в tenant B.

## 7. Negative Checks

- [ ] Попробовать использовать неверный `domain` и убедиться, что routing уходит в fallback/default tenant только там, где это ожидаемо.
- [ ] Попробовать сохранить занятый `slug` и занятый `domain` и убедиться, что API возвращает конфликт.
- [ ] Попробовать admin API с корректным Bearer key, но для чужого tenant slug, и убедиться, что доступ запрещён.

## 8. Recommended Command Smoke

- [ ] `pytest -q tests/integration/test_products_api.py tests/integration/test_order_flow.py tests/integration/test_admin_api.py tests/integration/test_admin_tenant_settings.py tests/integration/test_worker_consumer.py tests/test_admin_api_auth_integration.py tests/test_worker_period_inference.py`

## 9. Exit Criteria

- [ ] Tenant routing работает по `slug`.
- [ ] Tenant routing работает по `domain`.
- [ ] Admin key rotation работает и инвалидирует старый ключ.
- [ ] Storefront и admin изолированы между tenant-ами.
- [ ] Bot и worker используют tenant context по bot token.