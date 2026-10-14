"""Settings of the Market Data service, on top of the template's (all ``QS_*``)."""

from pydantic import SecretStr

from qs_template import ServiceSettings


class MarketSettings(ServiceSettings):
    service_name: str = "market"

    # Redis for the vendor request budget and the token revocation list
    redis_url: SecretStr
