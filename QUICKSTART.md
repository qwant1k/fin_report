# Quick Start

> **На вашей машине обнаружено**: Python 3.12 (`C:\Program Files\Python312\python.exe`),
> Node.js (`C:\Program Files\nodejs\`), Docker (`C:\Program Files\Docker\Docker\`).
> Они **установлены, но не в PATH** — поэтому `python --version` зависает.
> Используйте скрипты из `scripts\` (они вызывают абсолютные пути).

## 0. Подготовка

```powershell
copy .env.example .env
# отредактируйте секреты: SECRET_KEY, JWT_SECRET, ADMIN_PASSWORD, SMTP_*
```

## 1. Локальный запуск через скрипты (рекомендуется)

В корне проекта (`fund-reporting/`):

```powershell
# 1) один раз — установить зависимости (создаёт venv и качает npm-пакеты)
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1

# 2) запустить backend (в одном окне)
powershell -ExecutionPolicy Bypass -File .\scripts\backend.ps1

# 3) запустить frontend (в другом окне)
powershell -ExecutionPolicy Bypass -File .\scripts\frontend.ps1

# 4) опционально — прогнать тесты
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

- Swagger: <http://localhost:8000/docs>
- Health:  <http://localhost:8000/api/health>
- UI:      <http://localhost:5173>

## 1а. Локальный запуск вручную

Если хотите без скриптов — добавьте в PATH либо вызывайте абсолютные пути:

```powershell
# Backend
& 'C:\Program Files\Python312\python.exe' -m venv .\backend\.venv
.\backend\.venv\Scripts\Activate.ps1
pip install -r .\backend\requirements.txt
uvicorn main:app --reload --port 8000  # из папки backend

# Frontend
& 'C:\Program Files\nodejs\npm.cmd' install              # из папки frontend
& 'C:\Program Files\nodejs\npm.cmd' run dev
```

При первом запуске:
- создаются папки `data/uploads`, `data/reports`, `data/logs`
- создаётся SQLite БД `data/fund_reporting.db`
- засеиваются 4 ЧДУ (Halyk / BCC / Jusan / Centras), лимиты, формулы
- создаётся пользователь `admin / admin` (поменяйте после первого входа)

## 2. Docker Compose

```powershell
docker compose up --build
```
- Frontend: <http://localhost:8080>
- Backend:  <http://localhost:8000>
- Volume `kdif_backend_data` хранит БД и uploads

Для остановки:
```powershell
docker compose down            # сохранить данные
docker compose down -v         # удалить вместе с БД
```

## 3. Типичный сценарий

1. Войти как `admin`.
2. **Настройки → ЧДУ** — проверить, что все 4 ЧДУ перечислены и заданы префиксы участников KASE (`HALFN`, `BCC`, `JUSAN`, `CENTR`). При необходимости добавьте email для рассылки.
3. **Настройки → Лимиты** — отредактируйте лимиты по категориям инструментов.
4. **MBM** → «Обновить» (или ввести вручную) — забирает дюрацию/YTM benchmark.
5. **KASE** → выберите дату → «Обновить с KASE» — подтянет рыночные котировки.
6. **Загрузка** → drag-and-drop XLSX (TradeReport от ЧДУ). Парсер сам определит ЧДУ и дату; при необходимости поправьте вручную.
7. **Дашборд** → нажмите «Пересчитать». Получите все блоки ЧДУ с подсветкой нарушений.
8. **XLSX / PDF** — кнопки экспорта на дашборде.
9. **Алерты** — список нарушений; их можно отметить как решённые.
10. **Формулы** (admin) — drag-and-drop конструктор расчётных формул.
11. **Админ** — пользователи, роли, аудит-лог.

## 4. Расписание (APScheduler)

В `.env`:
- `KASE_FETCH_CRON_HOUR=18` `KASE_FETCH_CRON_MINUTE=0` — ежедневный fetch KASE
- В то же время + 5 мин подтягивается MBM

## 5. Email-уведомления

Заполните `SMTP_HOST/PORT/USER/PASSWORD` и `SMTP_FROM`. Тогда:
- При создании алертов с severity ≥ WARN, на `contact_email` ЧДУ уйдёт письмо.
- В конце расчёта (если есть нарушения) — на все active ЧДУ отправляется digest.

Если SMTP не сконфигурирован — система работает без писем, без ошибок.

## 6. Тесты

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

Реальный TradeReport-тест ищет файл `Trade report 1009 2025.xlsx` в `e:\projects\Сиуа\KDIF_FIN\` (родительская папка относительно `fund-reporting/`); если файла нет — тест автоматически пропустится.

## 7. Резервное копирование

SQLite БД лежит в `backend/data/fund_reporting.db` (или в Docker-томе `kdif_backend_data`). Достаточно скопировать этот файл вместе с папкой `uploads/` и `reports/`.
