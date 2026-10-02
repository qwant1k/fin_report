from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.db_models import (
    CDU,
    CDULimit,
    FormulaDefinition,
    InstrumentCategoryRule,
    RoleDefinition,
    User,
)
from seed import seed_startup_data


def test_admin_only_seed_leaves_business_and_reference_tables_empty():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        seed_startup_data(db, "admin_only")

        users = db.query(User).all()
        assert len(users) == 1
        assert users[0].role == "admin"
        assert users[0].is_active is True
        assert db.query(CDU).count() == 0
        assert db.query(CDULimit).count() == 0
        assert db.query(InstrumentCategoryRule).count() == 0
        assert db.query(FormulaDefinition).count() == 0
        assert db.query(RoleDefinition).count() == 0

    engine.dispose()
