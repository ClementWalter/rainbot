"""CAPTCHA solving service using 2Captcha API.

This module provides functionality to solve various types of CAPTCHAs
encountered on the Paris Tennis booking website.
"""

import ast
import base64
import json
import logging
import re
import tempfile
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from twocaptcha import TwoCaptcha
from twocaptcha.api import ApiException, NetworkException
from twocaptcha.solver import TimeoutException

from src.config.settings import settings

logger = logging.getLogger(__name__)

# Timeout settings
DEFAULT_CAPTCHA_TIMEOUT = 120  # seconds
RECAPTCHA_TIMEOUT = 180  # seconds for reCAPTCHA
LIVEIDENTITY_JS_VERSION = "v4"


@dataclass
class CaptchaSolveResult:
    """Result of a CAPTCHA solving attempt."""

    success: bool
    token: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class LiveIdentityConfig:
    """Configuration extracted for LiveIdentity anti-bot captcha."""

    captcha_type: str
    locale: str
    sp_key: str
    base_url: str
    antibot_id: Optional[str]
    request_id: Optional[str]
    raw_values: Optional[list] = None


class CaptchaSolverService:
    """
    Service for solving CAPTCHAs using 2Captcha API.

    Supports:
    - reCAPTCHA v2
    - reCAPTCHA v3
    - Image-based CAPTCHAs
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the CAPTCHA solver service.

        Args:
            api_key: 2Captcha API key. If not provided, uses settings.
        """
        self._api_key = api_key or settings.captcha.api_key
        self._solver: Optional[TwoCaptcha] = None

    @property
    def solver(self) -> TwoCaptcha:
        """Get or create the TwoCaptcha solver instance."""
        if self._solver is None:
            if not self._api_key:
                raise ValueError("CAPTCHA API key not configured")
            self._solver = TwoCaptcha(
                apiKey=self._api_key,
                defaultTimeout=DEFAULT_CAPTCHA_TIMEOUT,
                recaptchaTimeout=RECAPTCHA_TIMEOUT,
                pollingInterval=5,
            )
        return self._solver

    def get_balance(self) -> float:
        """
        Get the current 2Captcha account balance.

        Returns:
            Account balance in USD.

        Raises:
            ApiException: If API call fails.
        """
        try:
            return float(self.solver.balance())
        except (ApiException, NetworkException) as e:
            logger.error(f"Failed to get balance: {e}")
            raise

    def solve_recaptcha_v2(
        self,
        sitekey: str,
        url: str,
        invisible: bool = False,
    ) -> CaptchaSolveResult:
        """
        Solve a reCAPTCHA v2 challenge.

        Args:
            sitekey: The site key from the reCAPTCHA element.
            url: The URL of the page with the CAPTCHA.
            invisible: Whether the reCAPTCHA is invisible.

        Returns:
            CaptchaSolveResult with the token if successful.
        """
        try:
            logger.info(f"Solving reCAPTCHA v2 for {url}")
            result = self.solver.recaptcha(
                sitekey=sitekey,
                url=url,
                invisible=invisible,
            )
            logger.info("reCAPTCHA v2 solved successfully")
            return CaptchaSolveResult(success=True, token=result["code"])
        except TimeoutException:
            logger.error("reCAPTCHA solving timed out")
            return CaptchaSolveResult(success=False, error_message="CAPTCHA solving timed out")
        except ApiException as e:
            logger.error(f"2Captcha API error: {e}")
            return CaptchaSolveResult(success=False, error_message=str(e))
        except NetworkException as e:
            logger.error(f"Network error during CAPTCHA solve: {e}")
            return CaptchaSolveResult(success=False, error_message=f"Network error: {e}")

    def solve_recaptcha_v3(
        self,
        sitekey: str,
        url: str,
        action: str = "verify",
        min_score: float = 0.3,
    ) -> CaptchaSolveResult:
        """
        Solve a reCAPTCHA v3 challenge.

        Args:
            sitekey: The site key from the reCAPTCHA element.
            url: The URL of the page with the CAPTCHA.
            action: The action parameter from the reCAPTCHA.
            min_score: Minimum required score (0.1 to 0.9).

        Returns:
            CaptchaSolveResult with the token if successful.
        """
        try:
            logger.info(f"Solving reCAPTCHA v3 for {url}")
            result = self.solver.recaptcha(
                sitekey=sitekey,
                url=url,
                version="v3",
                action=action,
                score=min_score,
            )
            logger.info("reCAPTCHA v3 solved successfully")
            return CaptchaSolveResult(success=True, token=result["code"])
        except TimeoutException:
            logger.error("reCAPTCHA v3 solving timed out")
            return CaptchaSolveResult(success=False, error_message="CAPTCHA solving timed out")
        except ApiException as e:
            logger.error(f"2Captcha API error: {e}")
            return CaptchaSolveResult(success=False, error_message=str(e))
        except NetworkException as e:
            logger.error(f"Network error during CAPTCHA solve: {e}")
            return CaptchaSolveResult(success=False, error_message=f"Network error: {e}")

    def solve_image_captcha(
        self,
        image_path: str,
        case_sensitive: bool = False,
        numeric: Optional[int] = None,
        min_length: int = 0,
        max_length: int = 0,
    ) -> CaptchaSolveResult:
        """
        Solve an image-based CAPTCHA.

        Args:
            image_path: Path to the CAPTCHA image file or base64 string.
            case_sensitive: Whether the answer is case-sensitive.
            numeric: 1 for digits only, 2 for letters only, 0 for any.
            min_length: Minimum answer length.
            max_length: Maximum answer length.

        Returns:
            CaptchaSolveResult with the text answer if successful.
        """
        try:
            logger.info("Solving image CAPTCHA")
            params = {}
            if case_sensitive:
                params["caseSensitive"] = 1
            if numeric is not None:
                params["numeric"] = numeric
            if min_length > 0:
                params["minLength"] = min_length
            if max_length > 0:
                params["maxLength"] = max_length

            image_payload = image_path
            if isinstance(image_path, str):
                trimmed = image_path.strip()
                lower_trimmed = trimmed.lower()
                if lower_trimmed.startswith("data:"):
                    marker = "base64,"
                    marker_index = lower_trimmed.find(marker)
                    if marker_index == -1:
                        return CaptchaSolveResult(
                            success=False,
                            error_message="Unsupported data URI CAPTCHA format",
                        )
                    image_payload = trimmed[marker_index + len(marker) :].strip()
                    image_payload = "".join(image_payload.split())
                    if not image_payload:
                        return CaptchaSolveResult(
                            success=False,
                            error_message="Empty data URI CAPTCHA payload",
                        )
                elif trimmed.startswith(("http://", "https://")):
                    try:
                        response = requests.get(trimmed, timeout=30)
                        response.raise_for_status()
                    except requests.RequestException as e:
                        logger.error("Failed to fetch CAPTCHA image: %s", e)
                        return CaptchaSolveResult(
                            success=False,
                            error_message=f"Failed to fetch CAPTCHA image: {e}",
                        )
                    image_payload = base64.b64encode(response.content).decode("ascii")

            result = self.solver.normal(image_payload, **params)
            logger.info("Image CAPTCHA solved successfully")
            return CaptchaSolveResult(success=True, token=result["code"])
        except TimeoutException:
            logger.error("Image CAPTCHA solving timed out")
            return CaptchaSolveResult(success=False, error_message="CAPTCHA solving timed out")
        except ApiException as e:
            logger.error(f"2Captcha API error: {e}")
            return CaptchaSolveResult(success=False, error_message=str(e))
        except NetworkException as e:
            logger.error(f"Network error during CAPTCHA solve: {e}")
            return CaptchaSolveResult(success=False, error_message=f"Network error: {e}")

    def solve_captcha_from_page(
        self,
        driver: WebDriver,
        max_retries: int = 3,
    ) -> CaptchaSolveResult:
        """
        Detect and solve CAPTCHA on the current page.

        This method automatically detects the CAPTCHA type and solves it.

        Args:
            driver: Selenium WebDriver with the page loaded.
            max_retries: Maximum number of solve attempts.

        Returns:
            CaptchaSolveResult with success status.
        """
        current_url = driver.current_url
        last_error: Optional[CaptchaSolveResult] = None

        for attempt in range(1, max_retries + 1):
            logger.info(f"CAPTCHA solve attempt {attempt}/{max_retries}")

            # Try to detect LiveIdentity anti-bot CAPTCHA
            liveidentity_result = self._detect_and_solve_liveidentity_antibot(driver)
            if liveidentity_result is not None:
                if liveidentity_result.success:
                    return liveidentity_result
                last_error = liveidentity_result

            # Try to detect reCAPTCHA
            recaptcha_result = self._detect_and_solve_recaptcha(driver, current_url)
            if recaptcha_result is not None:
                if recaptcha_result.success:
                    return recaptcha_result
                # Continue to next attempt if failed
                last_error = recaptcha_result
                time.sleep(2)
                continue

            # Try to detect image CAPTCHA
            image_result = self._detect_and_solve_image_captcha(driver)
            if image_result is not None:
                if image_result.success:
                    return image_result
                # Continue to next attempt if failed
                last_error = image_result
                time.sleep(2)
                continue

            # No CAPTCHA detected
            if last_error is None:
                logger.info("No CAPTCHA detected on page")
                return CaptchaSolveResult(success=True, error_message="No CAPTCHA detected")
            time.sleep(2)

        if last_error is not None:
            return last_error
        return CaptchaSolveResult(
            success=False,
            error_message=f"Failed to solve CAPTCHA after {max_retries} attempts",
        )

    def _detect_and_solve_liveidentity_antibot(
        self,
        driver: WebDriver,
    ) -> Optional[CaptchaSolveResult]:
        """Detect and solve LiveIdentity anti-bot CAPTCHA if present."""
        try:
            has_antibot = False
            try:
                driver.find_element(By.ID, "li-antibot")
                has_antibot = True
            except NoSuchElementException:
                page_source = driver.page_source or ""
                if "LI_ANTIBOT.loadAntibot" in page_source:
                    has_antibot = True

            if not has_antibot:
                return None

            config = self._parse_liveidentity_config(driver.page_source or "")
            if not config:
                return CaptchaSolveResult(
                    success=False,
                    error_message="LiveIdentity captcha configuration not found",
                )

            existing_token = self._read_liveidentity_token(driver)
            if self._is_liveidentity_token_valid(existing_token):
                return CaptchaSolveResult(success=True, token=existing_token)

            refreshed_token = self._refresh_liveidentity_token(driver, config)
            if self._is_liveidentity_token_valid(refreshed_token):
                return CaptchaSolveResult(success=True, token=refreshed_token)

            solve_result = self._solve_liveidentity_antibot(config, driver=driver)
            if solve_result is None:
                return None
            if solve_result.success and solve_result.token:
                self._inject_liveidentity_token(driver, solve_result.token)
            return solve_result
        except WebDriverException as e:
            logger.error(f"WebDriver error detecting LiveIdentity CAPTCHA: {e}")
            return None

    def _parse_liveidentity_config(self, page_source: str) -> Optional[LiveIdentityConfig]:
        """Parse LiveIdentity config from page source."""
        raw_values = self._extract_liveidentity_config_array(page_source)
        if not raw_values:
            return None

        try:
            config_values = self._parse_liveidentity_config_values(raw_values)
        except (ValueError, TypeError):
            return None
        if not isinstance(config_values, list):
            return None

        def get_value(index: int) -> Optional[str]:
            if len(config_values) > index:
                return config_values[index]
            return None

        captcha_type = get_value(0) or "IMAGE"
        locale = get_value(2) or "fr"
        sp_key = get_value(3)
        base_url = get_value(4)
        if not sp_key or not base_url:
            return None

        return LiveIdentityConfig(
            captcha_type=captcha_type,
            locale=locale,
            sp_key=sp_key,
            base_url=base_url,
            antibot_id=get_value(7),
            request_id=get_value(8),
            raw_values=config_values,
        )

    def _extract_liveidentity_config_array(self, page_source: str) -> Optional[str]:
        """Extract the LiveIdentity config array from a loadAntibot call."""
        if not page_source:
            return None

        pattern = r"(?:window\.)?LI_ANTIBOT\.loadAntibot\s*\("
        for match in re.finditer(pattern, page_source):
            start = page_source.find("[", match.end())
            if start == -1:
                continue
            array_literal = self._extract_bracketed_array(page_source, start)
            if array_literal:
                return array_literal
        return None

    def _extract_bracketed_array(self, value: str, start: int) -> Optional[str]:
        """Return the bracketed array literal starting at a given index."""
        depth = 0
        in_single = False
        in_double = False
        escape = False

        for index in range(start, len(value)):
            ch = value[index]
            if escape:
                escape = False
                continue

            if ch == "\\":
                escape = True
                continue

            if ch == "'" and not in_double:
                in_single = not in_single
                continue

            if ch == '"' and not in_single:
                in_double = not in_double
                continue

            if in_single or in_double:
                continue

            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return value[start : index + 1]

        return None

    def _parse_liveidentity_config_values(self, raw_values: str) -> Optional[list]:
        """Parse LiveIdentity config values from a JavaScript array literal."""
        if not raw_values:
            return None

        try:
            parsed = json.loads(raw_values)
        except json.JSONDecodeError:
            parsed = None

        if parsed is not None:
            return parsed if isinstance(parsed, list) else None

        normalized = self._normalize_js_literal_tokens(raw_values)
        try:
            parsed = ast.literal_eval(normalized)
        except (ValueError, SyntaxError):
            return None
        return parsed if isinstance(parsed, list) else None

    def _normalize_js_literal_tokens(self, value: str) -> str:
        """Normalize JS literal tokens to Python equivalents outside quoted strings."""
        replacements = {
            "null": "None",
            "true": "True",
            "false": "False",
            "undefined": "None",
        }
        output: list[str] = []
        in_single = False
        in_double = False
        escape = False
        lowered = value.lower()
        i = 0
        length = len(value)

        while i < length:
            ch = value[i]
            if escape:
                output.append(ch)
                escape = False
                i += 1
                continue

            if ch == "\\":
                output.append(ch)
                escape = True
                i += 1
                continue

            if ch == "'" and not in_double:
                in_single = not in_single
                output.append(ch)
                i += 1
                continue

            if ch == '"' and not in_single:
                in_double = not in_double
                output.append(ch)
                i += 1
                continue

            if not in_single and not in_double:
                replaced = False
                for js_token, py_token in replacements.items():
                    if lowered.startswith(js_token, i) and self._is_token_boundary(
                        value, i, len(js_token)
                    ):
                        output.append(py_token)
                        i += len(js_token)
                        replaced = True
                        break
                if replaced:
                    continue

            output.append(ch)
            i += 1

        return "".join(output)

    def _is_token_boundary(self, value: str, start: int, length: int) -> bool:
        """Return True if a token is bounded by non-identifier characters."""

        def is_ident(ch: str) -> bool:
            return ch.isalnum() or ch in ("_", "$")

        before = value[start - 1] if start > 0 else ""
        after = value[start + length] if start + length < len(value) else ""
        return not is_ident(before) and not is_ident(after)

    def _read_liveidentity_token(self, driver: WebDriver) -> Optional[str]:
        """Read the LiveIdentity token from the page if present."""
        try:
            token = driver.execute_script("""
                const input = document.getElementById('li-antibot-token')
                    || document.querySelector(\"input[name='li-antibot-token']\");
                return input ? input.value : null;
                """)
        except WebDriverException:
            return None
        if not isinstance(token, str):
            return None
        token = token.strip()
        return token or None

    def _is_liveidentity_token_valid(self, token: Optional[str]) -> bool:
        """Return True if the LiveIdentity token is usable."""
        if not token or not isinstance(token, str):
            return False
        lowered = token.lower().strip()
        if not lowered:
            return False
        if "blacklist" in lowered or "invalid" in lowered:
            return False
        return lowered != "invalid response."

    def _refresh_liveidentity_token(
        self,
        driver: WebDriver,
        config: LiveIdentityConfig,
        timeout_seconds: int = 4,
    ) -> Optional[str]:
        """Attempt to refresh the LiveIdentity token using in-page JS helpers."""
        try:
            refreshed = driver.execute_script(
                """
                const configValues = arguments[0];
                const li = window.LI_ANTIBOT;
                if (!li) {
                    return { ok: false, reason: 'missing' };
                }

                let triedReload = false;
                if (typeof li.reloadAntibot === 'function') {
                    triedReload = true;
                    try {
                        li.reloadAntibot();
                        return { ok: true, method: 'reload' };
                    } catch (error) {
                        // Fall through to loadAntibot when reload fails.
                    }
                }

                if (typeof li.loadAntibot === 'function' && Array.isArray(configValues)) {
                    try {
                        li.loadAntibot(configValues);
                        return { ok: true, method: 'load', triedReload };
                    } catch (error) {
                        return { ok: false, reason: 'load-failed', triedReload };
                    }
                }

                return { ok: false, reason: 'unsupported', triedReload };
                """,
                config.raw_values if config else None,
            )
        except WebDriverException:
            return None

        if refreshed is True:
            refreshed_ok = True
        elif isinstance(refreshed, dict):
            refreshed_ok = bool(refreshed.get("ok"))
        else:
            refreshed_ok = False

        if not refreshed_ok:
            return None

        deadline = time.time() + max(1, timeout_seconds)
        while time.time() < deadline:
            token = self._read_liveidentity_token(driver)
            if self._is_liveidentity_token_valid(token):
                return token
            time.sleep(0.5)

        return None

    def _solve_liveidentity_antibot(
        self,
        config: LiveIdentityConfig,
        driver: Optional[WebDriver] = None,
    ) -> Optional[CaptchaSolveResult]:
        """Solve LiveIdentity anti-bot using the public API."""
        if str(config.captcha_type).upper() == "INVISIBLE_CAPTCHA":
            logger.info("LiveIdentity invisible CAPTCHA detected; falling back to other solvers")
            return None

        transaction = self._fetch_liveidentity_transaction(config)
        if not transaction:
            return CaptchaSolveResult(
                success=False,
                error_message="Failed to create LiveIdentity transaction",
            )

        if transaction.get("antibotMethod") == "INVISIBLE_CAPTCHA":
            logger.info(
                "LiveIdentity invisible CAPTCHA reported by API; falling back to other solvers"
            )
            return None

        challenge = self._fetch_liveidentity_challenge(config, transaction)
        if not challenge:
            return CaptchaSolveResult(
                success=False,
                error_message="Failed to load LiveIdentity challenge",
            )

        if challenge.get("captchaType") != "IMAGE":
            return CaptchaSolveResult(
                success=False,
                error_message=f"Unsupported LiveIdentity CAPTCHA type: {challenge.get('captchaType')}",
            )

        question_urls = challenge.get("questions") or []
        if not question_urls:
            return CaptchaSolveResult(
                success=False,
                error_message="LiveIdentity challenge returned no images",
            )

        question_url = str(question_urls[0]).strip()
        if not question_url:
            return CaptchaSolveResult(
                success=False,
                error_message="LiveIdentity challenge returned empty image URL",
            )

        base_url = config.base_url.rstrip("/") + "/"
        image_url = urljoin(base_url, question_url)

        image_payload = None
        if driver is not None:
            image_payload = self._fetch_captcha_image_data_url(driver, image_url)

        if image_payload:
            image_result = self.solve_image_captcha(image_payload)
        else:
            try:
                response = requests.get(image_url, timeout=30)
                response.raise_for_status()
            except requests.RequestException as e:
                return CaptchaSolveResult(
                    success=False, error_message=f"Failed to fetch captcha image: {e}"
                )

            with tempfile.NamedTemporaryFile(suffix=".png") as temp_file:
                temp_file.write(response.content)
                temp_file.flush()
                image_result = self.solve_image_captcha(temp_file.name)

        if not image_result.success or not image_result.token:
            return CaptchaSolveResult(
                success=False,
                error_message=image_result.error_message or "Image CAPTCHA solve failed",
            )

        validation = self._validate_liveidentity_answer(
            config=config,
            transaction=transaction,
            answer=image_result.token,
            validation_url=challenge.get("captchaValidationUrl"),
        )
        return validation

    def _fetch_liveidentity_transaction(self, config: LiveIdentityConfig) -> Optional[dict]:
        """Create a LiveIdentity transaction."""
        try:
            params = {}
            if config.antibot_id:
                params["antibotId"] = config.antibot_id
            if config.request_id:
                params["requestId"] = config.request_id

            response = requests.post(
                f"{config.base_url}/public/frontend/api/v3/captchas/transaction",
                params=params,
                headers={
                    "X-LI-sp-key": config.sp_key,
                    "X-LI-js-version": LIVEIDENTITY_JS_VERSION,
                },
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"LiveIdentity transaction error: {e}")
            return None
        except ValueError:
            return None

    def _fetch_liveidentity_challenge(
        self,
        config: LiveIdentityConfig,
        transaction: dict,
    ) -> Optional[dict]:
        """Fetch a LiveIdentity CAPTCHA challenge."""
        antibot_id = transaction.get("antibotId")
        request_id = transaction.get("requestId")
        if not antibot_id or not request_id:
            return None

        body = f"type={config.captcha_type}"
        try:
            response = requests.post(
                f"{config.base_url}/public/frontend/api/v3/captchas",
                data=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-LI-sp-key": config.sp_key,
                    "X-LI-request-id": request_id,
                    "X-LI-antibot-id": antibot_id,
                    "X-LI-js-version": LIVEIDENTITY_JS_VERSION,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            data["captchaType"] = config.captcha_type
            return data
        except requests.RequestException as e:
            logger.error(f"LiveIdentity challenge error: {e}")
            return None
        except ValueError:
            return None

    def _validate_liveidentity_answer(
        self,
        config: LiveIdentityConfig,
        transaction: dict,
        answer: str,
        validation_url: Optional[str],
    ) -> CaptchaSolveResult:
        """Validate a LiveIdentity CAPTCHA answer."""
        if not validation_url:
            return CaptchaSolveResult(success=False, error_message="Missing validation URL")

        request_id = transaction.get("requestId")
        antibot_id = transaction.get("antibotId")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-LI-sp-key": config.sp_key,
            "X-LI-js-version": LIVEIDENTITY_JS_VERSION,
        }
        if request_id:
            headers["X-LI-request-id"] = request_id
        if antibot_id:
            headers["X-LI-antibot-id"] = antibot_id

        try:
            response = requests.post(
                f"{config.base_url}{validation_url}",
                data=f"answer={requests.utils.quote(answer)}",
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as e:
            return CaptchaSolveResult(
                success=False, error_message=f"Captcha validation failed: {e}"
            )

        if response.status_code != 200:
            return CaptchaSolveResult(
                success=False,
                error_message=f"Captcha validation failed with status {response.status_code}",
            )

        try:
            data = response.json()
        except ValueError:
            return CaptchaSolveResult(success=False, error_message="Invalid validation response")

        if not isinstance(data, dict):
            return CaptchaSolveResult(success=False, error_message="Invalid validation response")

        error_code = data.get("errorCode") or data.get("error") or data.get("errorMessage")
        status = str(data.get("status") or "").strip().lower()
        message = str(data.get("message") or "").strip()

        def is_invalid(value: str) -> bool:
            lowered = value.lower()
            return "invalid" in lowered or "blacklist" in lowered

        if error_code:
            return CaptchaSolveResult(success=False, error_message=str(error_code))
        if status and any(key in status for key in ("invalid", "blacklist", "error")):
            return CaptchaSolveResult(success=False, error_message=f"CAPTCHA {status}")
        if message and is_invalid(message):
            return CaptchaSolveResult(success=False, error_message=message)

        token = data.get("antibotToken") or data.get("token") or data.get("message")
        if not token:
            return CaptchaSolveResult(success=False, error_message="Invalid CAPTCHA response")
        token_str = str(token).strip()
        if not token_str or token_str == "Invalid response." or is_invalid(token_str):
            return CaptchaSolveResult(success=False, error_message="Invalid CAPTCHA response")

        return CaptchaSolveResult(success=True, token=token_str)

    def _inject_liveidentity_token(self, driver: WebDriver, token: str) -> None:
        """Inject the LiveIdentity token into the page and trigger validation."""
        try:
            driver.execute_script(
                """
                const token = arguments[0];
                const tokenInput = document.getElementById('li-antibot-token');
                if (tokenInput) {
                    tokenInput.value = token;
                    tokenInput.setAttribute('value', token);
                    tokenInput.dispatchEvent(new Event('input', { bubbles: true }));
                    tokenInput.dispatchEvent(new Event('change', { bubbles: true }));
                }
                const container = document.getElementById('li-antibot');
                if (container) {
                    const event = new Event('change', { bubbles: true });
                    container.dispatchEvent(event);
                }
                if (typeof checkFormValidity === 'function') {
                    try {
                        checkFormValidity();
                    } catch (error) {
                        // Ignore validation errors; the submit handler will surface failures.
                    }
                }
                """,
                token,
            )
        except WebDriverException as e:
            logger.warning(f"Failed to inject LiveIdentity token: {e}")

    def _extract_recaptcha_sitekey(self, page_source: str) -> Optional[str]:
        """Extract a reCAPTCHA sitekey from page source."""
        if not page_source:
            return None

        patterns = [
            r"data-sitekey=['\"]([^'\"]+)['\"]",
            r"recaptcha/api\.js\?render=([^\"'&<>]+)",
            r"[?&]render=([^\"'&<>]+)",
            r"grecaptcha\.execute\(\s*['\"]([^'\"]+)['\"]",
            r"['\"]sitekey['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        ]

        for pattern in patterns:
            match = re.search(pattern, page_source, re.IGNORECASE)
            if not match:
                continue
            candidate = match.group(1).strip()
            if not candidate:
                continue
            if candidate.lower() in ("explicit", "onload"):
                continue
            return candidate

        return None

    def _extract_recaptcha_action(self, page_source: str) -> Optional[str]:
        """Extract a reCAPTCHA v3 action from page source."""
        if not page_source:
            return None

        match = re.search(
            r"grecaptcha\.execute\([^,]+,\s*\{\s*action\s*:\s*['\"]([^'\"]+)['\"]",
            page_source,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()

        return None

    def _detect_and_solve_recaptcha(
        self,
        driver: WebDriver,
        url: str,
    ) -> Optional[CaptchaSolveResult]:
        """Detect and solve reCAPTCHA if present."""
        try:
            # Look for reCAPTCHA iframe or container
            recaptcha_selectors = [
                "iframe[src*='recaptcha']",
                ".g-recaptcha",
                "[data-sitekey]",
            ]

            sitekey = None
            element_with_sitekey = None
            action = None
            invisible = False
            for selector in recaptcha_selectors:
                try:
                    element = driver.find_element(By.CSS_SELECTOR, selector)
                    sitekey = element.get_attribute("data-sitekey")
                    if not sitekey:
                        # Try to get from parent or iframe
                        parent = driver.find_element(By.CSS_SELECTOR, ".g-recaptcha")
                        sitekey = parent.get_attribute("data-sitekey")
                        if sitekey:
                            element = parent
                    if sitekey:
                        element_with_sitekey = element
                        break
                except NoSuchElementException:
                    continue

            page_source = driver.page_source or ""
            lower_source = page_source.lower()

            if element_with_sitekey is not None:
                try:
                    container = driver.find_element(By.CSS_SELECTOR, ".g-recaptcha")
                    if container.get_attribute("data-sitekey"):
                        element_with_sitekey = container
                except NoSuchElementException:
                    pass

                data_size = element_with_sitekey.get_attribute("data-size")
                action = element_with_sitekey.get_attribute("data-action")
                if data_size == "invisible":
                    invisible = True

            if not sitekey:
                sitekey = self._extract_recaptcha_sitekey(page_source)
            if not action:
                action = self._extract_recaptcha_action(page_source)

            if not sitekey:
                return None

            is_v3 = bool(action)
            if not is_v3 and (
                "grecaptcha.execute" in lower_source or "recaptcha/api.js?render=" in lower_source
            ):
                is_v3 = True

            if invisible:
                is_v3 = False

            if is_v3:
                result = self.solve_recaptcha_v3(sitekey, url, action=action or "verify")
            else:
                result = self.solve_recaptcha_v2(sitekey, url, invisible=invisible)

            if result.success and result.token:
                # Inject the token into the page
                self._inject_recaptcha_token(driver, result.token)

            return result

        except WebDriverException as e:
            logger.error(f"WebDriver error detecting reCAPTCHA: {e}")
            return None

    def _inject_recaptcha_token(self, driver: WebDriver, token: str) -> None:
        """Inject the solved reCAPTCHA token into the page."""
        try:
            # Escape token for safe JavaScript string injection
            escaped_token = json.dumps(token)
            # Standard g-recaptcha-response textarea
            driver.execute_script(f"""
                var token = {escaped_token};
                var fireEvent = function(element) {{
                    if (!element) {{
                        return;
                    }}
                    element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }};

                var elements = new Set();
                var textarea = document.getElementById('g-recaptcha-response');
                if (textarea) {{
                    elements.add(textarea);
                }}
                document.querySelectorAll('textarea[name="g-recaptcha-response"]').forEach(function(el) {{
                    elements.add(el);
                }});
                document.querySelectorAll('input[name="g-recaptcha-response"]').forEach(function(el) {{
                    elements.add(el);
                }});

                if (elements.size === 0) {{
                    var containers = Array.prototype.slice.call(document.querySelectorAll('form'));
                    if (!containers.length && document.body) {{
                        containers = [document.body];
                    }}
                    if (containers.length) {{
                        containers.forEach(function(container, index) {{
                            var fallback = document.createElement('textarea');
                            fallback.name = 'g-recaptcha-response';
                            fallback.id = index === 0
                                ? 'g-recaptcha-response'
                                : 'g-recaptcha-response-' + index;
                            fallback.style.display = 'none';
                            container.appendChild(fallback);
                            elements.add(fallback);
                        }});
                    }}
                }}

                elements.forEach(function(element) {{
                    try {{
                        element.value = token;
                        if (element.tagName && element.tagName.toLowerCase() === 'textarea') {{
                            element.innerHTML = token;
                        }}
                        fireEvent(element);
                    }} catch (e) {{
                        // Ignore individual element injection errors.
                    }}
                }});

                var callbackElement = document.querySelector(
                    '.g-recaptcha[data-callback], [data-sitekey][data-callback]'
                );
                if (callbackElement) {{
                    var callbackName = callbackElement.getAttribute('data-callback');
                    if (callbackName && typeof window[callbackName] === 'function') {{
                        try {{
                            window[callbackName](token);
                        }} catch (e) {{
                            // Ignore callback failures; page handlers will surface issues.
                        }}
                    }}
                }}

                if (typeof ___grecaptcha_cfg !== 'undefined' && ___grecaptcha_cfg.clients) {{
                    try {{
                        Object.values(___grecaptcha_cfg.clients).forEach(function(client) {{
                            var callback = null;
                            if (client && typeof client.callback === 'function') {{
                                callback = client.callback;
                            }} else if (client && client.hl && client.hl.l && client.hl.l.callback) {{
                                callback = client.hl.l.callback;
                            }}
                            if (typeof callback === 'function') {{
                                callback(token);
                            }}
                        }});
                    }} catch (e) {{
                        // Ignore callback discovery failures.
                    }}
                }}
                """)
            logger.info("reCAPTCHA token injected successfully")
        except WebDriverException as e:
            logger.warning(f"Failed to inject reCAPTCHA token: {e}")

    def _detect_and_solve_image_captcha(
        self,
        driver: WebDriver,
    ) -> Optional[CaptchaSolveResult]:
        """Detect and solve image CAPTCHA if present."""
        try:
            # Look for common image CAPTCHA patterns
            image_selectors = [
                "#captcha img",
                ".captcha-image img",
                "img[alt*='captcha']",
                "img[src*='captcha']",
            ]

            captcha_image = None
            for selector in image_selectors:
                try:
                    captcha_image = driver.find_element(By.CSS_SELECTOR, selector)
                    break
                except NoSuchElementException:
                    continue

            if captcha_image is None:
                return None

            # Get image source
            img_src = captcha_image.get_attribute("src")
            if not img_src:
                return None
            parsed_src = urlparse(img_src)
            if not parsed_src.scheme and driver.current_url:
                img_src = urljoin(driver.current_url, img_src)

            # Fetch through the browser to include session cookies when possible.
            data_url = self._fetch_captcha_image_data_url(driver, img_src)
            if data_url:
                result = self.solve_image_captcha(data_url)
            else:
                result = self.solve_image_captcha(img_src)

            if result.success and result.token:
                # Find and fill the input field
                self._fill_captcha_input(driver, result.token)

            return result

        except WebDriverException as e:
            logger.error(f"WebDriver error detecting image CAPTCHA: {e}")
            return None

    def _fetch_captcha_image_data_url(
        self,
        driver: WebDriver,
        img_src: str,
    ) -> Optional[str]:
        """Fetch CAPTCHA image as a data URL using the browser context."""
        if not img_src:
            return None
        if str(img_src).strip().lower().startswith("data:"):
            return img_src
        try:
            result = driver.execute_async_script(
                """
                const url = arguments[0];
                const callback = arguments[arguments.length - 1];
                if (!url) {
                    callback({ ok: false, error: "missing url" });
                    return;
                }
                fetch(url, { credentials: "include" })
                    .then((response) => {
                        if (!response.ok) {
                            throw new Error(`HTTP ${response.status}`);
                        }
                        return response.blob();
                    })
                    .then((blob) => new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result);
                        reader.onerror = () => reject(new Error("read failed"));
                        reader.readAsDataURL(blob);
                    }))
                    .then((dataUrl) => callback({ ok: true, dataUrl }))
                    .catch((error) => callback({ ok: false, error: String(error) }));
                """,
                img_src,
            )
        except WebDriverException:
            return None

        if not isinstance(result, dict) or not result.get("ok"):
            return None
        data_url = result.get("dataUrl")
        if isinstance(data_url, str) and data_url.startswith("data:"):
            return data_url
        return None

    def _fill_captcha_input(self, driver: WebDriver, answer: str) -> None:
        """Fill the CAPTCHA answer input field."""
        try:
            input_selectors = [
                "#captcha-input",
                "input[name='captcha']",
                "input[name='captchaAnswer']",
                ".captcha-input",
            ]

            for selector in input_selectors:
                try:
                    input_field = driver.find_element(By.CSS_SELECTOR, selector)
                    input_field.clear()
                    input_field.send_keys(answer)
                    logger.info("CAPTCHA answer filled successfully")
                    return
                except NoSuchElementException:
                    continue

            logger.warning("Could not find CAPTCHA input field")
        except WebDriverException as e:
            logger.warning(f"Failed to fill CAPTCHA input: {e}")


# Global service instance (lazy initialization)
_captcha_service: Optional[CaptchaSolverService] = None


def get_captcha_service() -> CaptchaSolverService:
    """Get the global CAPTCHA solver service instance."""
    global _captcha_service
    if _captcha_service is None:
        _captcha_service = CaptchaSolverService()
    return _captcha_service
