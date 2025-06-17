import logging
import base64
import json
import httpx
import os
from decimal import Decimal
from typing import TypedDict, Protocol, Callable, Literal
from enum import StrEnum
from urllib.parse import urlparse, quote_plus

from cdp.auth.utils.jwt import generate_jwt, JwtOptions
from pydantic import BaseModel, Field
from fasthtml.common import *
from starlette import status

logger = logging.getLogger(__name__)


X402_VERSION = 1
COINBASE_FACILITATOR_BASE_URL = "https://api.cdp.coinbase.com"
COINBASE_FACILITATOR_V2_ROUTE = "/platform/v2/x402"
MIXED_ADDRESS_REGEX = r"^0x[a-fA-F0-9]{40}|[A-Za-z0-9][A-Za-z0-9-]{0,34}[A-Za-z0-9]$"


class FacilitatorConfig(BaseModel):
    url: str
    create_auth_headers: Callable[[], dict] | None = None

class PaymentMiddlewareOptions(TypedDict):
    description: str
    mime_type: str
    max_timeout_seconds: int
    output_schema: dict
    facilitator_config: FacilitatorConfig
    testnet: bool
    custom_paywall_html: str
    resource: str
    resource_root_url: str


class Scheme(StrEnum):
    exact = "exact"


class Network(StrEnum):
    base = "base"
    base_sepolia = "base-sepolia"


class PaymentRequirements(BaseModel):
    scheme: Scheme
    network: Network
    max_amount_required: str = Field(serialization_alias="maxAmountRequired")
    resource: str
    description: str
    mime_type: str = Field(serialization_alias="mimeType")
    output_schema: dict | None = Field(serialization_alias="outputSchema", default=None)
    pay_to: str = Field(serialization_alias="payTo", pattern=MIXED_ADDRESS_REGEX)
    max_timeout_seconds: int = Field(serialization_alias="maxTimeoutSeconds")
    asset: str = Field(pattern=MIXED_ADDRESS_REGEX)
    extra: dict = Field(default={})

class VerifyResponse(BaseModel):
    is_valid: bool = Field(alias="isValid")
    invalid_reason: str | None = Field(alias="invalidReason", default=None)
    payer: str | None = None


class FacilitatorClientProtocol(Protocol):
    def __init__(self, config: FacilitatorConfig): ...
    def verify(self, payment_payload: dict, payment_requirements: PaymentRequirements) -> dict: ...
    def settle(self, payment_payload: dict, payment_requirements: PaymentRequirements) -> dict: ...


class FacilitatorClient(FacilitatorClientProtocol):
    DEFAULT_FACILITATOR_URL = f"{COINBASE_FACILITATOR_BASE_URL}{COINBASE_FACILITATOR_V2_ROUTE}"

    def __init__(self, config: FacilitatorConfig | None = None):
        if config is None:
            config = FacilitatorConfig(url=self.DEFAULT_FACILITATOR_URL)
        self.client = httpx.AsyncClient()
        self.config = config

    async def _send_request(self, action: Literal["verify", "settle"], payment_payload: dict, payment_requirements: PaymentRequirements) -> dict:
        body = {
            "x402Version": X402_VERSION,
            "paymentPayload": payment_payload,
            "paymentRequirements": payment_requirements.model_dump(by_alias=True, exclude_none=True),
        }

        headers = {
            "Content-Type": "application/json",
        }
        if self.config.create_auth_headers:
            auth_headers = self.config.create_auth_headers() # Call once
            specific_auth = auth_headers.get(action, {}) # Get specific auth dict
            for key, value in specific_auth.items():
                headers[key] = value
        
        response = await self.client.post(f"{self.config.url}/{action}", json=body, headers=headers)
        response.raise_for_status() # Raise an exception for bad status codes
        return response.json()

    async def verify(self, payment_payload: dict, payment_requirements: PaymentRequirements) -> VerifyResponse:
        response_json = await self._send_request("verify", payment_payload, payment_requirements)
        return VerifyResponse(**response_json)

    async def settle(self, payment_payload: dict, payment_requirements: PaymentRequirements) -> dict:
        return await self._send_request("settle", payment_payload, payment_requirements)


def create_auth_header(cdp_key_name: str, cdp_private_key: str, base_url: str, path: str) -> str:
    host = base_url.replace("https://", "")
    jwt = generate_jwt(
        JwtOptions(
            api_key_id=cdp_key_name,
            api_key_secret=cdp_private_key,
            request_method="POST",
            request_host=host,
            request_path=path,
        )
    )
    return f"Bearer {jwt}"


def create_correlation_header() -> str:
    data = {
        "sdk_version": "0.0.0",
        "sdk_language": "python",
        "source": "fewsats",
        "source_version": "0.1.0",
    }
    pairs = [f"{k}={quote_plus(str(v))}" for k, v in data.items()]
    return ",".join(pairs)


def create_x402_auth_headers() -> dict:
    cdp_key_name = os.environ.get("CDP_KEY_NAME")
    cdp_private_key = os.environ.get("CDP_PRIVATE_KEY")
    if not cdp_key_name or not cdp_private_key:
        raise ValueError("Missing credentials: CDP_KEY_NAME and CDP_PRIVATE_KEY must be set")
    
    verify_path = f"{COINBASE_FACILITATOR_V2_ROUTE}/verify"
    settle_path = f"{COINBASE_FACILITATOR_V2_ROUTE}/settle"

    verify_token = create_auth_header(cdp_key_name, cdp_private_key, COINBASE_FACILITATOR_BASE_URL, verify_path)
    settle_token = create_auth_header(cdp_key_name, cdp_private_key, COINBASE_FACILITATOR_BASE_URL, settle_path)
    correlation_header = create_correlation_header()
    return {
        "verify": {"Authorization": verify_token, "Correlation-Context": correlation_header},
        "settle": {"Authorization": settle_token, "Correlation-Context": correlation_header},
    }


def create_x402_facilitator_config() -> FacilitatorConfig:
    return FacilitatorConfig(
        url=FacilitatorClient.DEFAULT_FACILITATOR_URL,
        create_auth_headers=create_x402_auth_headers
    )


def decode_payment_payload(payment: str) -> dict:
    decodedBytes = base64.b64decode(payment)
    payload = json.loads(decodedBytes)
    payload["x402Version"] = 1
    return payload


def encode_to_base64(data: dict) -> str:
    return base64.b64encode(json.dumps(data).encode()).decode()


def get_paywall_html(options: PaymentMiddlewareOptions) -> str:
    return "<html><body>Payment Required</body></html>"


async def payment_middleware(url: str, x_payment: str | None, user_agent: str | None, accept_header: str | None, amount: Decimal, address: str, **kwargs: PaymentMiddlewareOptions) -> Response:

    default_options = {
        "facilitator_config": FacilitatorConfig(url=FacilitatorClient.DEFAULT_FACILITATOR_URL),
        "max_timeout_seconds": 300,
        "testnet": True,
    }

    options = {**default_options, **kwargs}

    network = "base"
    usdc_address = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    facilitator_client = FacilitatorClient(options["facilitator_config"])
    max_amount_required = int(amount * 10**6)

    if options["testnet"]:
        network = "base-sepolia"
        usdc_address = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


    logger.info("Payment middleware checking request", extra={"url": url})
    is_web_browser = accept_header and "text/html" in accept_header and user_agent and "Mozilla" in user_agent
    resource = options.get("resource", options.get("resource_root_url", "") + urlparse(url).path)

    payment_requirements = PaymentRequirements(
        scheme=Scheme.exact,
        network=network,
        max_amount_required=str(max_amount_required),
        resource=resource,
        description=options.get("description", ""),
        mime_type=options.get("mime_type", ""),
        pay_to=address,
        max_timeout_seconds=options["max_timeout_seconds"],
        asset=usdc_address,
        output_schema=options.get("output_schema", None),
        extra={
            "name": "USDC" if options["testnet"] else "USD Coin",
            "version": "2",
        }
    )

    try:
        payment_payload = decode_payment_payload(x_payment)
    except Exception as e:
        if is_web_browser:
            html = options.get("custom_paywall_html")
            if not html:
                html = get_paywall_html(options)

            return HTMLResponse(content=html, status_code=status.HTTP_402_PAYMENT_REQUIRED)

        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "error": "X-PAYMENT header is required",
                "accepts": [payment_requirements.model_dump(by_alias=True, exclude_none=True)],
                "x402Version": X402_VERSION,
            }
        )

    payment_payload["x402Version"] = X402_VERSION

    try:
        verify_response = await facilitator_client.verify(payment_payload, payment_requirements)
    except Exception as e:
        logger.error("failed to verify", extra={"error": e})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": str(e),
                "x402Version": X402_VERSION,
            }
        )

    if not verify_response.is_valid:
        logger.error("Invalid payment", extra={"invalid_reason": verify_response.invalid_reason})
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "error": verify_response.invalid_reason,
                "accepts": [payment_requirements.model_dump(by_alias=True, exclude_none=True)],
                "x402Version": X402_VERSION,
            }
        )
    
    logger.info("Payment verified, proceeding")
    try:
        settle_response = await facilitator_client.settle(payment_payload, payment_requirements)
    except Exception as e:
        logger.error("Settlement failed", extra={"error": e})
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "error": str(e),
                "accepts": [payment_requirements.model_dump(by_alias=True, exclude_none=True)],
                "x402Version": X402_VERSION,
            }
        )
    
    try:
        settle_reponse_header = encode_to_base64(settle_response)
    except Exception as e:
        logger.error("Settle Header Encoding Failed", extra={"error": e})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": str(e),
                "x402Version": X402_VERSION,
            }
        )
    
    return Response(
        status_code=status.HTTP_200_OK,
        headers={
            "X-PAYMENT-RESPONSE": settle_reponse_header,
        }
    )
