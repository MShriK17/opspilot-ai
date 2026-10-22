"""Settings read from environment variables (12-factor style)."""
import os


class Settings:
    def __init__(self) -> None:
        self.service_name = os.getenv("SERVICE_NAME", "target-app")
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./target_app.db")
        self.log_file = os.getenv("LOG_FILE", "")
        self.admin_token = os.getenv("ADMIN_TOKEN", "dev-token")
        self.payment_timeout_s = float(os.getenv("PAYMENT_TIMEOUT_S", "3.0"))
        self.pool_timeout_s = float(os.getenv("POOL_TIMEOUT_S", "1.0"))
        self.leak_limit_mb = int(os.getenv("LEAK_LIMIT_MB", "400"))


settings = Settings()
