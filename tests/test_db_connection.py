from sqlalchemy import text
from app.core.database import engine
from app.core.config import settings


def test_mysql_connection():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar_one()
        assert result == 1

        current_db = conn.execute(text("SELECT DATABASE()")).scalar_one()
        assert current_db == settings.mysql_db