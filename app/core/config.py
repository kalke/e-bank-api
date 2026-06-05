import os


class Settings:
    def __init__(self) -> None:
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://ebank:ebank@localhost:5432/ebank",
        )
        self.database_url_test = os.getenv(
            "DATABASE_URL_TEST",
            "sqlite+aiosqlite:///:memory:",
        )


settings = Settings()
