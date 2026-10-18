from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_AMIN_SECRET = "dev-secret-change-me"
MIN_SECRET_LEN = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    RAFIQ_ENV: str = "dev"  # dev|prod
    RAFIQ_LIVE: str = "sim"  # sim|real
    RAFIQ_ROUTER: str = "rules"  # rules|llm
    RAFIQ_MCP_MODE: str = "inproc"  # inproc|http
    RAFIQ_QUORUM: int = 1
    RAFIQ_AMIN_SECRET: str = DEFAULT_AMIN_SECRET
    RAFIQ_FLEET_URL: str = ""

    # Auth / pilot hardening
    RAFIQ_DEV_AUTH: bool = False  # X-Role/X-Reviewer header auth - dev env only
    RAFIQ_SESSION_TTL_HOURS: int = 12
    RAFIQ_RATE_LIMIT_PER_MINUTE: int = 60
    RAFIQ_LOGIN_RATE_LIMIT_PER_MINUTE: int = 5
    RAFIQ_TRUSTED_HOSTS: str = ""  # comma separated; empty = allow all (dev)
    # Public base URL (e.g. https://rafiq.example) used in sitemap.xml/robots.txt
    # when the app sits behind a TLS proxy; empty = derive from the request.
    RAFIQ_PUBLIC_URL: str = ""
    RAFIQ_TLS_CERT: str = ""
    RAFIQ_TLS_KEY: str = ""
    RAFIQ_SECURE_COOKIES: bool = False  # forced on in prod

    # Sign-off env vars are kept inert for backward compatibility with older
    # deployments (owner decision 2026-10-18: no sign-off requirement).
    RAFIQ_REQUIRE_VERIFIED: bool = False
    RAFIQ_PILOT_UNVERIFIED: bool = False

    OPENAI_BASE_URL: str = ""
    OPENAI_MODEL: str = ""
    OPENAI_API_KEY: str = ""

    def is_prod(self) -> bool:
        return self.RAFIQ_ENV.lower() == "prod"

    def cookie_secure(self) -> bool:
        return self.RAFIQ_SECURE_COOKIES or self.is_prod()

    def requires_verified(self) -> bool:
        """Sign-off is no longer a serving requirement.

        Owner decision 2026-10-18: real book text is always served, plainly
        labelled «منقول من الكتب - بلا توقيع مفتٍ - المصدر: ...» with the
        mandatory "ليست فتوى مفتٍ معتمد" banner. Kept inert so deployments
        with old env vars (RAFIQ_REQUIRE_VERIFIED / RAFIQ_PILOT_UNVERIFIED)
        keep working without surprise behaviour.
        """
        return False

    def trusted_hosts(self) -> list[str]:
        return [h.strip() for h in self.RAFIQ_TRUSTED_HOSTS.split(",") if h.strip()]

    def validate_production(self) -> None:
        problems = []
        if self.is_prod():
            if (
                self.RAFIQ_AMIN_SECRET == DEFAULT_AMIN_SECRET
                or len(self.RAFIQ_AMIN_SECRET) < MIN_SECRET_LEN
            ):
                problems.append(
                    f"RAFIQ_AMIN_SECRET must be random and at least {MIN_SECRET_LEN} chars in prod"
                )
            if self.RAFIQ_DEV_AUTH:
                problems.append("RAFIQ_DEV_AUTH must be disabled in prod")
            if not self.trusted_hosts():
                problems.append("RAFIQ_TRUSTED_HOSTS must be set in prod")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


settings = Settings()
