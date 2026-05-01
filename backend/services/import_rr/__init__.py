"""Импортёр исторических Risk Report XLSM файлов.

Этот пакет извлекает данные из ежедневных XLSM-файлов Risk Report,
которые формирует ОИУА с помощью макроса Space X в оригинальной книге Excel.

Источник: e:/projects/Сиуа/KDIF_FIN/Примеры/Материалы от СИУА/Risk report/<MM.YYYY>/risk report_DDMMYYYY_.xlsm

Извлекаемые сущности:
- CashSnapshot (лист Cash)
- MVSnapshot (лист MV)
- InstrumentReference (лист Справочник)
- FXRate (лист Нацбанк Казахстана, Доллар США_)
- PortfolioSummary / PortfolioPosition (вкладка Report)
- BondLot (вкладки ГЦБ / Агентские / МФО / Ин.ЦБ)
- RepoLot (вкладка Repo)
- DepositLot (вкладка Dep)
- AccountReceivable (вкладка Accounts receivable / Дебиторская задолженность)
"""
from .risk_report_importer import (  # noqa: F401
    ImportResult,
    import_risk_report,
    import_folder,
    extract_date_from_filename,
)
