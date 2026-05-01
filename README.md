# Fund Reporting — KDIF / КФГД

Веб-приложение для автоматизации обработки торговых отчётов (TradeReport) от ЧДУ
(Halyk Finance, BCC Invest, Jusan Invest, Centras Securities) и формирования
сводного отчёта Фонда КФГД с проверкой инвестиционных лимитов.

## Архитектура

- **Backend**: Python 3.11+ / FastAPI / SQLAlchemy / SQLite, openpyxl, pandas, httpx, APScheduler
- **Frontend**: React + Vite + TypeScript, TailwindCSS, Recharts, TanStack Table, React-Dropzone, Zustand
- **Деплой**: docker-compose (backend + frontend в отдельных сервисах)

## Быстрый старт (без Docker)

### Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload --port 8000
```

Swagger UI: <http://localhost:8000/docs>

### Frontend
```powershell
cd frontend
npm install
npm run dev
```

UI: <http://localhost:5173>

## Быстрый старт (Docker)
```powershell
docker compose up --build
```

## Бизнес-цепочка

1. **Загрузка** — ЧДУ присылают XLSX (выгрузка KASE-сделок), фронт грузит файлы
   через drag-and-drop, бекенд парсит и сохраняет.
2. **Парсинг** — `services/parser/trade_report_parser.py` распознаёт ЧДУ,
   нормализует казахстанские числа, фильтрует исполненные сделки (Статус "+"),
   дедуплицирует строки одной сделки (Разм/К/П).
3. **Position book** — `services/calculator/position_builder.py` строит книгу
   позиций: открытые РЕПО, удерживаемые бумаги, денежный остаток.
4. **Оценка** — `portfolio_calculator.py` считает CMV, Daily Change, YTM,
   Duration по категориям инструментов (Cash / ГЦБ МФ РК / Обратное РЕПО /
   МФО ≥А− / Агентские ≥ВВ− / Дебиторка).
5. **KASE** — `services/kase/` тянет котировки и YTM для сверки.
6. **MBM** — `services/mbm/` тянет benchmark duration и YTM.
7. **Лимиты** — `limit_checker.py` валидирует Min/Max/Hard/Soft, рождает алерты.
8. **Отчёт** — `xlsx_generator.py` рисует точную копию Excel-макета (заголовок
   ЧДУ #1F6B38, REPO жёлтый #FFFF00, Total #70AD47, нарушения #FF0000).
9. **Дашборд** — фронтенд показывает KPI, графики, таблицу, алерты.
10. **Админка** — управление справочниками, лимитами, формулами, пользователями.

## Структура

```
fund-reporting/
├── backend/                 # FastAPI приложение
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── scheduler.py
│   ├── api/routes/          # upload, calculate, dashboard, kase, mbm, export, settings, admin
│   ├── services/
│   │   ├── parser/          # парсер TradeReport, числа, валидация
│   │   ├── calculator/      # позиции, CMV/YTM/Duration, лимиты
│   │   ├── kase/            # KASE клиент + HTML fallback
│   │   ├── mbm/             # MBM index клиент
│   │   ├── report/          # XLSX/PDF генераторы
│   │   └── alerts/
│   ├── models/              # db_models.py, schemas.py
│   ├── tests/
│   └── requirements.txt
├── frontend/                # React + Vite
├── docker-compose.yml
├── .env.example
└── README.md
```

## Лицензия

Проприетарное ПО для КФГД.
