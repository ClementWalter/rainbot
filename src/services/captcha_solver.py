"""CAPTCHA solving service using 2Captcha API.

This module provides functionality to solve various types of CAPTCHAs
encountered on the Paris Tennis booking website.
"""

import ast
import asyncio
import base64
import json
import logging
import re
import tempfile
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional
from urllib.parse import urljoin, urlparse

import requests
from twocaptcha import TwoCaptcha
from twocaptcha.api import ApiException, NetworkException
from twocaptcha.solver import TimeoutException

from src.config.settings import settings

if TYPE_CHECKING:
    from playwright.async_api import Page

# Try to import Selenium, but make it optional for Playwright-only usage
try:
    from selenium.common.exceptions import NoSuchElementException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.remote.webdriver import WebDriver

    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    NoSuchElementException = Exception
    WebDriverException = Exception
    By = None
    WebDriver = None

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

    async def solve_recaptcha_v2_async(
        self,
        sitekey: str,
        url: str,
        invisible: bool = False,
    ) -> CaptchaSolveResult:
        """Async wrapper for solve_recaptcha_v2 that runs in a thread pool."""
        return await asyncio.to_thread(
            self.solve_recaptcha_v2,
            sitekey,
            url,
            invisible,
        )

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

    async def solve_recaptcha_v3_async(
        self,
        sitekey: str,
        url: str,
        action: str = "verify",
        min_score: float = 0.3,
    ) -> CaptchaSolveResult:
        """Async wrapper for solve_recaptcha_v3 that runs in a thread pool."""
        return await asyncio.to_thread(
            self.solve_recaptcha_v3,
            sitekey,
            url,
            action,
            min_score,
        )

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

    async def solve_image_captcha_async(
        self,
        image_path: str,
        case_sensitive: bool = False,
        numeric: Optional[int] = None,
        min_length: int = 0,
        max_length: int = 0,
    ) -> CaptchaSolveResult:
        """Async wrapper for solve_image_captcha that runs in a thread pool."""
        return await asyncio.to_thread(
            self.solve_image_captcha,
            image_path,
            case_sensitive,
            numeric,
            min_length,
            max_length,
        )

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
            if solve_result is not None and solve_result.success and solve_result.token:
                self._inject_liveidentity_token(driver, solve_result.token)
                return solve_result

            # Fallback: try to extract and solve the image directly from the iframe
            iframe_result = self._solve_liveidentity_iframe_captcha(driver)
            if iframe_result is not None:
                return iframe_result

            # Return API error if iframe fallback also failed
            if solve_result is not None:
                return solve_result
            return None
        except WebDriverException as e:
            logger.error(f"WebDriver error detecting LiveIdentity CAPTCHA: {e}")
            return None

    def _solve_liveidentity_iframe_captcha(self, driver: WebDriver) -> Optional[CaptchaSolveResult]:
        """Extract and solve LiveIdentity captcha image from the iframe.

        This method uses Selenium's native iframe switching and element screenshot
        to bypass cross-origin restrictions that prevent JavaScript access.
        """
        try:
            # Find the iframe element in the main page
            try:
                iframe = driver.find_element(By.CSS_SELECTOR, "#li-antibot iframe")
            except NoSuchElementException:
                logger.debug("No LiveIdentity iframe found")
                return None

            logger.info("Found LiveIdentity iframe, switching to extract captcha image")

            # Switch to the iframe context
            driver.switch_to.frame(iframe)

            try:
                # Find the captcha image inside the iframe
                try:
                    img = driver.find_element(By.CSS_SELECTOR, "img")
                except NoSuchElementException:
                    logger.debug("No captcha image found inside LiveIdentity iframe")
                    return None

                # Take a screenshot of the image element (bypasses cross-origin restrictions)
                img_base64 = img.screenshot_as_base64
                if not img_base64:
                    logger.debug("Failed to capture screenshot of captcha image")
                    return None

                logger.info(f"Captured captcha image screenshot ({len(img_base64)} bytes base64)")

                # Solve the captcha using 2captcha
                solve_result = self.solve_image_captcha(img_base64)
                if not solve_result.success:
                    logger.warning(f"Failed to solve captcha image: {solve_result.error_message}")
                    return solve_result

                # Enter the answer into the input field while still in iframe context
                answer = solve_result.token
                if answer:
                    # Need to re-switch to iframe as the context might have changed
                    driver.switch_to.default_content()
                    time.sleep(0.5)
                    iframe = driver.find_element(By.CSS_SELECTOR, "#li-antibot iframe")
                    driver.switch_to.frame(iframe)

                    try:
                        # Use specific LiveIdentity input ID
                        input_field = driver.find_element(By.CSS_SELECTOR, "#li-antibot-answer")
                        input_field.clear()
                        input_field.send_keys(answer)
                        logger.info(f"Entered captcha answer: {answer}")

                        # Click the validate button using specific ID
                        try:
                            validate_btn = driver.find_element(
                                By.CSS_SELECTOR, "#li-antibot-validate"
                            )
                            validate_btn.click()
                            logger.info("Clicked captcha validate button")
                        except NoSuchElementException:
                            # Fallback to generic button search
                            buttons = driver.find_elements(
                                By.CSS_SELECTOR, "button, input[type='submit']"
                            )
                            for btn in buttons:
                                btn_text = (btn.text or btn.get_attribute("value") or "").lower()
                                if any(
                                    word in btn_text
                                    for word in ("valid", "submit", "ok", "envoyer")
                                ):
                                    btn.click()
                                    logger.info("Clicked captcha submit button")
                                    break

                    except NoSuchElementException:
                        logger.warning("Could not find input field in captcha iframe")

                # Switch back to main content to check for the token
                driver.switch_to.default_content()

                # Wait for the token to be populated after captcha submission
                for _ in range(10):  # Wait up to 5 seconds
                    time.sleep(0.5)
                    token = self._read_liveidentity_token(driver)
                    if self._is_liveidentity_token_valid(token):
                        logger.info("LiveIdentity token obtained after captcha solve")
                        return CaptchaSolveResult(success=True, token=token)

                # Even if we don't have a token yet, the captcha was solved
                logger.info("Captcha solved but token not yet populated")
                return solve_result

            finally:
                # Always switch back to the main content
                driver.switch_to.default_content()

        except WebDriverException as e:
            logger.error(f"Error solving LiveIdentity iframe captcha: {e}")
            # Make sure we're back in the main content even if there was an error
            try:
                driver.switch_to.default_content()
            except WebDriverException:
                pass
            return None

    def _enter_liveidentity_iframe_answer(self, driver: WebDriver, answer: str) -> bool:
        """Enter the solved captcha answer into the LiveIdentity iframe input field."""
        try:
            result = driver.execute_script(
                """
                const answer = arguments[0];
                const liContainer = document.getElementById('li-antibot');
                if (!liContainer) return {success: false, error: 'no container'};

                const iframe = liContainer.querySelector('iframe');
                if (!iframe) return {success: false, error: 'no iframe'};

                try {
                    const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
                    if (!iframeDoc) return {success: false, error: 'no iframe doc'};

                    // Find the input field
                    const input = iframeDoc.querySelector('input[type="text"]');
                    if (!input) return {success: false, error: 'no input'};

                    // Enter the answer
                    input.value = answer;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));

                    // Try to find and click the submit/validate button
                    const buttons = iframeDoc.querySelectorAll('button, input[type="submit"]');
                    for (const btn of buttons) {
                        const text = (btn.textContent || btn.value || '').toLowerCase();
                        if (text.includes('valid') || text.includes('submit') || text.includes('ok')) {
                            btn.click();
                            break;
                        }
                    }

                    return {success: true};
                } catch(e) {
                    return {success: false, error: e.toString()};
                }
                """,
                answer,
            )

            if result and result.get("success"):
                logger.info("Successfully entered LiveIdentity captcha answer")
                # Wait for the token to be populated
                time.sleep(2)
                # Read the token that should now be set
                token = self._read_liveidentity_token(driver)
                if self._is_liveidentity_token_valid(token):
                    return True
            return False
        except WebDriverException as e:
            logger.error(f"Error entering LiveIdentity iframe answer: {e}")
            return False

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
        invalid_markers = ("blacklist", "invalid", "error", "erreur")
        if any(marker in lowered for marker in invalid_markers):
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

        # Get page URL for Origin/Referer headers
        page_url = None
        if driver is not None:
            try:
                page_url = driver.current_url
            except WebDriverException:
                pass

        transaction = self._fetch_liveidentity_transaction(config, page_url=page_url)
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

        challenge = self._fetch_liveidentity_challenge(config, transaction, page_url=page_url)
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
            page_url=page_url,
        )
        return validation

    def _fetch_liveidentity_transaction(
        self, config: LiveIdentityConfig, page_url: Optional[str] = None
    ) -> Optional[dict]:
        """Create a fresh LiveIdentity transaction.

        Note: We don't pass the antibot_id/request_id from the page config because
        those IDs are only valid for the initial page load. Creating a new transaction
        requires letting the server generate fresh IDs.
        """
        try:
            # Build headers with browser-like Origin and Referer
            headers = {
                "X-LI-sp-key": config.sp_key,
                "X-LI-js-version": LIVEIDENTITY_JS_VERSION,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            # Add Origin and Referer from page URL if available
            if page_url:
                parsed = urlparse(page_url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                headers["Origin"] = origin
                headers["Referer"] = page_url

            # Request body with captcha type and locale
            body = f"type={config.captcha_type}&locale={config.locale}"

            response = requests.post(
                f"{config.base_url}/public/frontend/api/v3/captchas/transaction",
                data=body,
                headers=headers,
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
        page_url: Optional[str] = None,
    ) -> Optional[dict]:
        """Fetch a LiveIdentity CAPTCHA challenge."""
        antibot_id = transaction.get("antibotId")
        request_id = transaction.get("requestId")
        if not antibot_id or not request_id:
            return None

        body = f"type={config.captcha_type}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-LI-sp-key": config.sp_key,
            "X-LI-request-id": request_id,
            "X-LI-antibot-id": antibot_id,
            "X-LI-js-version": LIVEIDENTITY_JS_VERSION,
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        # Add Origin and Referer from page URL if available
        if page_url:
            parsed = urlparse(page_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            headers["Origin"] = origin
            headers["Referer"] = page_url

        try:
            response = requests.post(
                f"{config.base_url}/public/frontend/api/v3/captchas",
                data=body,
                headers=headers,
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
        page_url: Optional[str] = None,
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
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if request_id:
            headers["X-LI-request-id"] = request_id
        if antibot_id:
            headers["X-LI-antibot-id"] = antibot_id
        # Add Origin and Referer from page URL if available
        if page_url:
            parsed = urlparse(page_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            headers["Origin"] = origin
            headers["Referer"] = page_url

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
        if not token_str or token_str == "Invalid response." or is_invalid(token_str):  # nosec B105
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

    # =========================================================================
    # Async Playwright methods
    # =========================================================================

    async def solve_captcha_from_page_async(
        self,
        page: "Page",
        max_retries: int = 3,
    ) -> CaptchaSolveResult:
        """
        Detect and solve CAPTCHA on the current page using Playwright.

        This method automatically detects the CAPTCHA type and solves it.

        Args:
            page: Playwright Page with the page loaded.
            max_retries: Maximum number of solve attempts.

        Returns:
            CaptchaSolveResult with success status.

        """
        from playwright.async_api import Error as PlaywrightError

        current_url = page.url
        last_error: Optional[CaptchaSolveResult] = None

        for attempt in range(1, max_retries + 1):
            logger.info(f"CAPTCHA solve attempt {attempt}/{max_retries}")

            # Try to detect image CAPTCHA FIRST (most common on Paris Tennis)
            image_result = await self._detect_and_solve_image_captcha_async(page)
            if image_result is not None:
                if image_result.success:
                    return image_result
                last_error = image_result
                await asyncio.sleep(2)
                continue

            # Try to detect reCAPTCHA
            recaptcha_result = await self._detect_and_solve_recaptcha_async(page, current_url)
            if recaptcha_result is not None:
                if recaptcha_result.success:
                    return recaptcha_result
                last_error = recaptcha_result
                await asyncio.sleep(2)
                continue

            # Try to detect LiveIdentity anti-bot CAPTCHA (usually invisible/background)
            liveidentity_result = await self._detect_and_solve_liveidentity_antibot_async(page)
            if liveidentity_result is not None:
                if liveidentity_result.success:
                    return liveidentity_result
                last_error = liveidentity_result

            # No CAPTCHA detected
            if last_error is None:
                logger.info("No CAPTCHA detected on page")
                return CaptchaSolveResult(success=True, error_message="No CAPTCHA detected")
            await asyncio.sleep(2)

        if last_error is not None:
            return last_error
        return CaptchaSolveResult(
            success=False,
            error_message=f"Failed to solve CAPTCHA after {max_retries} attempts",
        )

    async def _detect_and_solve_liveidentity_antibot_async(
        self,
        page: "Page",
    ) -> Optional[CaptchaSolveResult]:
        """Detect and solve LiveIdentity anti-bot CAPTCHA if present (async)."""
        from playwright.async_api import Error as PlaywrightError

        try:
            # Check for LiveIdentity iframe
            iframe_locator = page.locator("#li-antibot-iframe")
            if await iframe_locator.count() == 0:
                # Check for li-antibot div
                li_antibot = page.locator("#li-antibot")
                if await li_antibot.count() == 0:
                    return None
                # Wait for iframe to appear
                await asyncio.sleep(1)
                if await iframe_locator.count() == 0:
                    return None

            logger.info("Found LiveIdentity iframe captcha")

            # First try to solve via iframe directly
            iframe_result = await self._solve_liveidentity_iframe_async(page)
            if iframe_result and iframe_result.success:
                return iframe_result

            # Fallback to API-based solving
            page_source = await page.content()
            config = self._parse_liveidentity_config(page_source)
            if config:
                existing_token = await self._read_liveidentity_token_async(page)
                if self._is_liveidentity_token_valid(existing_token):
                    return CaptchaSolveResult(success=True, token=existing_token)

                solve_result = self._solve_liveidentity_antibot(config)
                if solve_result is not None and solve_result.success and solve_result.token:
                    await self._inject_liveidentity_token_async(page, solve_result.token)
                    return solve_result

            return CaptchaSolveResult(
                success=False,
                error_message="LiveIdentity solve not successful",
            )

        except PlaywrightError as e:
            logger.debug(f"Error detecting LiveIdentity captcha: {e}")
            return None

    async def _solve_liveidentity_iframe_async(
        self,
        page: "Page",
    ) -> Optional[CaptchaSolveResult]:
        """Solve LiveIdentity captcha by accessing the iframe directly."""
        from playwright.async_api import Error as PlaywrightError

        # Track captured token from network response
        captured_token_data: dict = {"token": None, "code": None}

        async def handle_response(response):
            """Intercept LiveIdentity validation response to capture token."""
            try:
                url = response.url
                if "liveidentity" in url and ("validate" in url or "captcha" in url):
                    logger.debug(f"LiveIdentity response: {url} status={response.status}")
                    if response.status == 200:
                        try:
                            data = await response.json()
                            logger.debug(
                                f"LiveIdentity response data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}"
                            )
                            if isinstance(data, dict):
                                # Try various field names for token and code
                                token = (
                                    data.get("antibotToken")
                                    or data.get("token")
                                    or data.get("li-antibot-token")
                                    or data.get("accessToken")
                                )
                                code = (
                                    data.get("antibotTokenCode")
                                    or data.get("code")
                                    or data.get("li-antibot-token-code")
                                    or data.get("tokenCode")
                                )

                                # Capture code from checkInvisibleCaptcha response (has 'code' field)
                                if code and not captured_token_data.get("code"):
                                    captured_token_data["code"] = code
                                    logger.info(f"Captured code from network: {code}")

                                # Capture token from /check response (has 'antibotToken' field)
                                if token:
                                    captured_token_data["token"] = token
                                    logger.info(f"Captured token from network: {token[:30]}...")
                                    if not captured_token_data.get("code"):
                                        logger.warning(
                                            f"Token captured but no code yet, full data: {data}"
                                        )
                        except Exception as e:
                            logger.debug(f"Failed to parse LiveIdentity response: {e}")
            except Exception as e:
                logger.debug(f"Error handling response: {e}")

        # Set up response interception
        page.on("response", handle_response)

        try:
            iframe_locator = page.locator("#li-antibot-iframe")
            if await iframe_locator.count() == 0:
                return None

            # Get the frame content
            frame_handle = await iframe_locator.element_handle()
            if not frame_handle:
                return None

            frame = await frame_handle.content_frame()
            if not frame:
                logger.warning("Could not access LiveIdentity iframe content")
                return None

            # Wait for content to load
            await asyncio.sleep(1)

            # Find the captcha image inside the iframe
            imgs = frame.locator("img")
            img_count = await imgs.count()
            logger.debug(f"Found {img_count} images in LiveIdentity iframe")

            captcha_img = None
            img_src = None
            for i in range(img_count):
                img = imgs.nth(i)
                src = await img.get_attribute("src")
                if src and "captcha" in src.lower() and await img.is_visible():
                    captcha_img = img
                    img_src = src
                    break

            if not captcha_img or not img_src:
                logger.warning("No captcha image found in LiveIdentity iframe")
                return None

            logger.info(f"Found LiveIdentity captcha image: {img_src[:60]}...")

            # Take a screenshot of the captcha image element (bypasses cross-origin and session issues)
            try:
                img_bytes = await captcha_img.screenshot()
                img_base64 = base64.b64encode(img_bytes).decode("ascii")
                logger.info(f"Captured captcha image screenshot ({len(img_base64)} bytes)")
            except PlaywrightError as e:
                logger.warning(f"Failed to screenshot captcha image, falling back to URL: {e}")
                img_base64 = None

            # Solve the image captcha (use async version to avoid blocking event loop)
            if img_base64:
                result = await self.solve_image_captcha_async(img_base64)
            else:
                result = await self.solve_image_captcha_async(img_src)
            if not result.success or not result.token:
                logger.error(f"Failed to solve LiveIdentity image: {result.error_message}")
                return result

            logger.info(f"Solved LiveIdentity captcha: {result.token}")

            # Set up postMessage listener on parent page BEFORE clicking validate
            # This captures the token that the iframe sends back
            await page.evaluate("""() => {
                window.__liAntibotCapturedToken = null;
                window.__liAntibotCapturedCode = null;
                window.addEventListener('message', function liAntibotMsgHandler(event) {
                    // LiveIdentity sends token via postMessage
                    if (event.data && typeof event.data === 'object') {
                        const data = event.data;
                        if (data.antibotToken || data.token) {
                            window.__liAntibotCapturedToken = data.antibotToken || data.token;
                            window.__liAntibotCapturedCode = data.antibotTokenCode || data.code || '';
                            console.log('Captured LiveIdentity token via postMessage:', window.__liAntibotCapturedToken);
                        }
                        // Also check for li-antibot specific message format
                        if (data.type === 'li-antibot-token' || data.action === 'setToken') {
                            window.__liAntibotCapturedToken = data.token || data.value;
                            window.__liAntibotCapturedCode = data.code || '';
                        }
                    }
                    // Some implementations send token as string
                    if (typeof event.data === 'string' && event.data.length > 20) {
                        // Could be a raw token
                        if (!event.data.startsWith('{') && !event.data.startsWith('<')) {
                            window.__liAntibotCapturedToken = event.data;
                        }
                    }
                }, false);
            }""")
            logger.debug("Set up postMessage listener for token capture")

            # Fill in the answer in the iframe
            answer_input = frame.locator("#li-antibot-answer")
            if await answer_input.count() > 0:
                await answer_input.fill(result.token)
                logger.debug("Filled captcha answer in iframe")

                # Click validate button
                validate_btn = frame.locator("#li-antibot-validate")
                if await validate_btn.count() > 0:
                    await validate_btn.click()
                    logger.info("Clicked validate button in iframe")

                    # Wait and poll for token from multiple sources
                    for wait_attempt in range(8):  # 8 seconds total
                        await asyncio.sleep(1)

                        # Check for token captured via network interception (most reliable)
                        if captured_token_data.get("token"):
                            token = captured_token_data["token"]
                            # Use the captcha answer as the code - this is what li-antibot-token-code expects
                            code = result.token  # The captcha answer (e.g., "jmset")
                            logger.info(f"Got token via network capture: {token[:30]}...")
                            await self._inject_liveidentity_token_async(page, token)
                            # Inject the captcha answer as the code into the form
                            await page.evaluate(
                                """(code) => {
                                    // Find the form to append inputs to
                                    const form = document.getElementById('formCaptcha')
                                        || document.querySelector('form[action*="reservation"]')
                                        || document.querySelector('form');

                                    const codeInput = document.getElementById('li-antibot-token-code')
                                        || document.querySelector("input[name='li-antibot-token-code']");
                                    if (codeInput) {
                                        codeInput.value = code;
                                        console.log('Injected li-antibot-token-code:', code);
                                    } else {
                                        // Create the input if it doesn't exist - add to form
                                        const input = document.createElement('input');
                                        input.type = 'hidden';
                                        input.name = 'li-antibot-token-code';
                                        input.id = 'li-antibot-token-code';
                                        input.value = code;
                                        if (form) {
                                            form.appendChild(input);
                                            console.log('Created and injected li-antibot-token-code to form:', code);
                                        } else {
                                            document.body.appendChild(input);
                                            console.log('Created and injected li-antibot-token-code to body:', code);
                                        }
                                    }
                                }""",
                                code,
                            )
                            logger.info(f"Injected li-antibot-token-code (captcha answer): {code}")

                            # Trigger the LI_ANTIBOT callback to enable the submit button
                            await page.evaluate(
                                """(token) => {
                                    console.log('Triggering LI_ANTIBOT callbacks...');
                                    // Try various methods to trigger the validation success callback
                                    if (typeof LI_ANTIBOT !== 'undefined') {
                                        console.log('LI_ANTIBOT found, keys:', Object.keys(LI_ANTIBOT));
                                        if (LI_ANTIBOT.onSuccess) {
                                            LI_ANTIBOT.onSuccess(token);
                                            console.log('Called LI_ANTIBOT.onSuccess');
                                        }
                                        if (LI_ANTIBOT.callback) {
                                            LI_ANTIBOT.callback(token);
                                            console.log('Called LI_ANTIBOT.callback');
                                        }
                                        if (LI_ANTIBOT.setToken) {
                                            LI_ANTIBOT.setToken(token);
                                            console.log('Called LI_ANTIBOT.setToken');
                                        }
                                        if (LI_ANTIBOT.setValidated) {
                                            LI_ANTIBOT.setValidated(true);
                                            console.log('Called LI_ANTIBOT.setValidated');
                                        }
                                    }
                                    // Try to enable submit button directly
                                    const submitBtn = document.getElementById('submitControle')
                                        || document.querySelector('button[type="submit"]')
                                        || document.querySelector('.btn-primary[type="submit"]')
                                        || document.querySelector('button.btn-next');
                                    if (submitBtn) {
                                        submitBtn.disabled = false;
                                        submitBtn.removeAttribute('disabled');
                                        submitBtn.classList.remove('disabled');
                                        console.log('Enabled submit button:', submitBtn.id || submitBtn.className);
                                    }
                                    // Dispatch events that might trigger UI updates
                                    window.dispatchEvent(new CustomEvent('li-antibot-validated'));
                                    window.dispatchEvent(new CustomEvent('li-antibot-success'));
                                    document.dispatchEvent(new Event('captcha-success'));
                                }""",
                                token,
                            )
                            logger.info("Triggered LI_ANTIBOT callbacks")

                            page.remove_listener("response", handle_response)
                            return CaptchaSolveResult(success=True, token=token)

                        # Check for captured token via postMessage
                        captured = await page.evaluate("""() => {
                            return {
                                token: window.__liAntibotCapturedToken,
                                code: window.__liAntibotCapturedCode
                            };
                        }""")
                        if captured and captured.get("token"):
                            logger.info(
                                f"Got token via postMessage capture: {captured['token'][:20]}..."
                            )
                            # Inject the captured token into the form
                            await self._inject_liveidentity_token_async(page, captured["token"])
                            if captured.get("code"):
                                await page.evaluate(
                                    """(code) => {
                                        const codeInput = document.getElementById('li-antibot-token-code')
                                            || document.querySelector("input[name='li-antibot-token-code']");
                                        if (codeInput) codeInput.value = code;
                                    }""",
                                    captured["code"],
                                )
                            page.remove_listener("response", handle_response)
                            return CaptchaSolveResult(success=True, token=captured["token"])

                        # Also check standard token input
                        token_value = await self._read_liveidentity_token_async(page)
                        if self._is_liveidentity_token_valid(token_value):
                            logger.info("LiveIdentity captcha solved successfully via iframe")
                            page.remove_listener("response", handle_response)
                            return CaptchaSolveResult(success=True, token=token_value)

                    # Token still not populated - try to trigger LI_ANTIBOT callback manually
                    logger.debug("Trying to trigger LI_ANTIBOT callback manually")
                    try:
                        # Check if iframe shows success message
                        success_indicators = frame.locator(
                            ".li-antibot-success, .success, [class*='success']"
                        )
                        if await success_indicators.count() > 0:
                            logger.info("Iframe shows success indicator")

                        # Try to extract token from iframe's hidden inputs
                        iframe_token = await frame.evaluate("""() => {
                            const tokenInput = document.querySelector('input[name*="token"], input[type="hidden"]');
                            return tokenInput ? tokenInput.value : null;
                        }""")
                        if iframe_token and len(str(iframe_token)) > 10:
                            logger.info(
                                f"Found token in iframe hidden input: {iframe_token[:20]}..."
                            )
                            await self._inject_liveidentity_token_async(page, iframe_token)
                            return CaptchaSolveResult(success=True, token=iframe_token)

                        # Try to trigger the callback with the solved answer
                        await page.evaluate(
                            """(answer) => {
                                // Try various methods to trigger token population
                                if (typeof LI_ANTIBOT !== 'undefined') {
                                    console.log('LI_ANTIBOT object:', Object.keys(LI_ANTIBOT));
                                    if (LI_ANTIBOT.validateAnswer) {
                                        LI_ANTIBOT.validateAnswer(answer);
                                    }
                                    if (LI_ANTIBOT.onValidationSuccess) {
                                        LI_ANTIBOT.onValidationSuccess();
                                    }
                                    if (LI_ANTIBOT.setValidated) {
                                        LI_ANTIBOT.setValidated(true);
                                    }
                                }
                                // Also try dispatching a custom event
                                window.dispatchEvent(new CustomEvent('li-antibot-validated'));
                                window.dispatchEvent(new CustomEvent('li-antibot-success'));
                            }""",
                            result.token,
                        )
                        await asyncio.sleep(1)

                        # Final check for token
                        token_value = await self._read_liveidentity_token_async(page)
                        if self._is_liveidentity_token_valid(token_value):
                            logger.info("LiveIdentity token obtained after manual trigger")
                            page.remove_listener("response", handle_response)
                            return CaptchaSolveResult(success=True, token=token_value)

                        # Check network capture one more time
                        if captured_token_data.get("token"):
                            token = captured_token_data["token"]
                            logger.info(
                                f"Got token via network capture after trigger: {token[:30]}..."
                            )
                            await self._inject_liveidentity_token_async(page, token)
                            page.remove_listener("response", handle_response)
                            return CaptchaSolveResult(success=True, token=token)
                    except PlaywrightError as e:
                        logger.debug(f"Manual trigger failed: {e}")

                    logger.warning("Token not populated after iframe solve")

            # Clean up listener
            page.remove_listener("response", handle_response)
            return CaptchaSolveResult(success=True, token=result.token)

        except PlaywrightError as e:
            logger.error(f"Error solving LiveIdentity iframe captcha: {e}")
            # Clean up listener on error
            try:
                page.remove_listener("response", handle_response)
            except Exception:
                pass
            return None

    async def _read_liveidentity_token_async(self, page: "Page") -> Optional[str]:
        """Read the existing LiveIdentity token from the page (async)."""
        from playwright.async_api import Error as PlaywrightError

        try:
            token_input = page.locator("input[name='li-antibot-token']")
            if await token_input.count() > 0:
                return await token_input.first.input_value() or None
        except PlaywrightError:
            pass
        return None

    async def _refresh_liveidentity_token_async(
        self,
        page: "Page",
        config: LiveIdentityConfig,
    ) -> Optional[str]:
        """Try to refresh the LiveIdentity token via JS (async)."""
        from playwright.async_api import Error as PlaywrightError

        try:
            await page.evaluate("""() => {
                    if (typeof LI_ANTIBOT !== 'undefined' && LI_ANTIBOT.loadAntibot) {
                        LI_ANTIBOT.loadAntibot();
                    }
                }""")
            await asyncio.sleep(2)
            return await self._read_liveidentity_token_async(page)
        except PlaywrightError as e:
            logger.debug(f"Failed to refresh LiveIdentity token: {e}")
            return None

    async def _inject_liveidentity_token_async(self, page: "Page", token: str) -> None:
        """Inject the solved LiveIdentity token into the page (async)."""
        from playwright.async_api import Error as PlaywrightError

        try:
            await page.evaluate(
                """(token) => {
                    // Find the form to append inputs to
                    const form = document.getElementById('formCaptcha')
                        || document.querySelector('form[action*="reservation"]')
                        || document.querySelector('form');

                    let tokenInput = document.querySelector('input[name="li-antibot-token"]');
                    if (tokenInput) {
                        tokenInput.value = token;
                        console.log('Updated existing li-antibot-token');
                    } else {
                        // Create the input if it doesn't exist
                        tokenInput = document.createElement('input');
                        tokenInput.type = 'hidden';
                        tokenInput.name = 'li-antibot-token';
                        tokenInput.id = 'li-antibot-token';
                        tokenInput.value = token;
                        if (form) {
                            form.appendChild(tokenInput);
                            console.log('Created and injected li-antibot-token to form');
                        } else {
                            document.body.appendChild(tokenInput);
                            console.log('Created and injected li-antibot-token to body');
                        }
                    }
                    if (typeof LI_ANTIBOT !== 'undefined' && LI_ANTIBOT.setToken) {
                        LI_ANTIBOT.setToken(token);
                    }
                }""",
                token,
            )
            logger.info("LiveIdentity token injected")
        except PlaywrightError as e:
            logger.warning(f"Failed to inject LiveIdentity token: {e}")

    async def _detect_and_solve_recaptcha_async(
        self,
        page: "Page",
        current_url: str,
    ) -> Optional[CaptchaSolveResult]:
        """Detect and solve reCAPTCHA if present (async)."""
        from playwright.async_api import Error as PlaywrightError

        try:
            page_source = await page.content()
            sitekey = self._extract_recaptcha_sitekey(page_source)
            if not sitekey:
                return None

            logger.info(f"reCAPTCHA detected with sitekey: {sitekey[:20]}...")

            # Detect version
            is_v3 = "grecaptcha.execute" in page_source or "recaptcha/api.js?render=" in page_source
            action = self._extract_recaptcha_action(page_source) if is_v3 else None

            if is_v3:
                result = await self.solve_recaptcha_v3_async(
                    sitekey, current_url, action=action or "verify"
                )
            else:
                result = await self.solve_recaptcha_v2_async(sitekey, current_url)

            if result.success and result.token:
                await self._inject_recaptcha_token_async(page, result.token)

            return result

        except PlaywrightError as e:
            logger.error(f"Error detecting reCAPTCHA: {e}")
            return None

    async def _inject_recaptcha_token_async(self, page: "Page", token: str) -> None:
        """Inject the solved reCAPTCHA token into the page (async)."""
        from playwright.async_api import Error as PlaywrightError

        try:
            await page.evaluate(
                """(token) => {
                    const textarea = document.querySelector('#g-recaptcha-response');
                    if (textarea) {
                        textarea.value = token;
                        textarea.style.display = 'block';
                    }
                    const callback = window.___grecaptcha_cfg?.clients?.[0]?.callback;
                    if (typeof callback === 'function') {
                        callback(token);
                    }
                }""",
                token,
            )
            logger.info("reCAPTCHA token injected")
        except PlaywrightError as e:
            logger.warning(f"Failed to inject reCAPTCHA token: {e}")

    async def _detect_and_solve_image_captcha_async(
        self,
        page: "Page",
    ) -> Optional[CaptchaSolveResult]:
        """Detect and solve image CAPTCHA if present (async)."""
        from playwright.async_api import Error as PlaywrightError

        try:
            # Look for common image CAPTCHA patterns
            # Paris Tennis uses a box with "Vérification de sécurité" header
            image_selectors = [
                "#captcha img",
                "#captchaImage",
                ".captcha-image img",
                "img[alt*='captcha']",
                "img[alt*='Captcha']",
                "img[src*='captcha']",
                "img[src*='Captcha']",
                "img[src*='JCaptcha']",
                "img[src*='jcaptcha']",
                ".security-verification img",
                # Paris Tennis specific: the verification box contains an img
                "fieldset img",
                "form img[src*='Captcha']",
                "form img[src*='captcha']",
                # Look for any img inside a container with "sécurité" text nearby
                ".verification-container img",
                "[class*='captcha'] img",
                "[class*='Captcha'] img",
                # Generic: any img that might be a captcha
                "#captcha > img",
                ".captcha img",
            ]

            captcha_image = None
            for selector in image_selectors:
                try:
                    locator = page.locator(selector)
                    count = await locator.count()
                    logger.debug(f"Checking selector '{selector}': found {count} elements")
                    if count > 0:
                        # Check if image is visible
                        if await locator.first.is_visible():
                            captcha_image = locator.first
                            logger.info(f"Found captcha image with selector: {selector}")
                            break
                except PlaywrightError as e:
                    logger.debug(f"Selector '{selector}' failed: {e}")
                    continue

            # Fallback: look for any visible img in the page that looks like a captcha
            if captcha_image is None:
                try:
                    page_content = await page.content()
                    if "sécurité" in page_content.lower() or "captcha" in page_content.lower():
                        # Try to find any img that's visible and looks like a captcha
                        all_imgs = page.locator("img:visible")
                        img_count = await all_imgs.count()
                        # Limit to first 20 images to avoid slow iteration
                        max_images_to_check = min(img_count, 20)
                        logger.debug(
                            f"Fallback: checking {max_images_to_check} of {img_count} visible images"
                        )
                        for i in range(max_images_to_check):
                            img = all_imgs.nth(i)
                            try:
                                # Use short timeout to avoid hanging
                                src = (
                                    await asyncio.wait_for(img.get_attribute("src"), timeout=2.0)
                                    or ""
                                )
                                # Skip tracking pixels, icons, logos, and common non-captcha images
                                skip_patterns = [
                                    "logo",
                                    "icon",
                                    "pixel",
                                    "tracking",
                                    ".svg",
                                    "favicon",
                                    "mdp",
                                    "paris.fr/tennis/jsp/site/images/",
                                    "header",
                                    "footer",
                                    "banner",
                                    "button",
                                    "arrow",
                                ]
                                if any(skip in src.lower() for skip in skip_patterns):
                                    continue  # Don't log every skip

                                # Check if src contains captcha-related keywords
                                captcha_keywords = ["captcha", "jcaptcha", "verify", "securit"]
                                is_likely_captcha = any(
                                    kw in src.lower() for kw in captcha_keywords
                                )

                                # Check image size with timeout - captcha images are usually larger than icons
                                try:
                                    box = await asyncio.wait_for(img.bounding_box(), timeout=2.0)
                                except asyncio.TimeoutError:
                                    continue
                                if box and box["width"] > 80 and box["height"] > 25:
                                    if is_likely_captcha or (
                                        box["width"] < 300 and box["height"] < 100
                                    ):
                                        # Likely a captcha: right size range and/or contains keywords
                                        captcha_image = img
                                        logger.info(
                                            f"Found captcha image via fallback: {src[:60]}..."
                                        )
                                        break
                            except (PlaywrightError, asyncio.TimeoutError):
                                continue
                except PlaywrightError as e:
                    logger.debug(f"Fallback image detection failed: {e}")

            if captcha_image is None:
                return None

            # Get image source
            img_src = await captcha_image.get_attribute("src")
            if not img_src:
                return None

            logger.info(f"Detected image CAPTCHA: {img_src[:60]}...")

            parsed_src = urlparse(img_src)
            if not parsed_src.scheme:
                img_src = urljoin(page.url, img_src)

            # Fetch through the browser to include session cookies
            data_url = await self._fetch_captcha_image_data_url_async(page, img_src)
            if data_url:
                result = await self.solve_image_captcha_async(data_url)
            else:
                result = await self.solve_image_captcha_async(img_src)

            if result.success and result.token:
                # Find and fill the input field
                await self._fill_captcha_input_async(page, result.token)

            return result

        except PlaywrightError as e:
            logger.error(f"Playwright error detecting image CAPTCHA: {e}")
            return None

    async def _fetch_captcha_image_data_url_async(
        self,
        page: "Page",
        img_src: str,
    ) -> Optional[str]:
        """Fetch CAPTCHA image as a data URL using the browser context (async)."""
        from playwright.async_api import Error as PlaywrightError

        if not img_src:
            return None
        if str(img_src).strip().lower().startswith("data:"):
            return img_src
        try:
            data_url = await page.evaluate(
                """async (src) => {
                    try {
                        const resp = await fetch(src, { credentials: 'include' });
                        if (!resp.ok) return null;
                        const blob = await resp.blob();
                        return new Promise((resolve) => {
                            const reader = new FileReader();
                            reader.onloadend = () => resolve(reader.result);
                            reader.readAsDataURL(blob);
                        });
                    } catch {
                        return null;
                    }
                }""",
                img_src,
            )
            return data_url
        except PlaywrightError as e:
            logger.debug(f"Failed to fetch image data URL: {e}")
            return None

    async def _fill_captcha_input_async(self, page: "Page", answer: str) -> None:
        """Fill the CAPTCHA answer into the input field (async)."""
        from playwright.async_api import Error as PlaywrightError

        try:
            input_selectors = [
                "#captcha-input",
                "input[name='captcha']",
                "input[name='captcha_response']",
                "input[type='text'][id*='captcha']",
                "input[type='text'][name*='captcha']",
                ".captcha-answer",
                "input.captcha-input",
                # Paris Tennis specific
                "input[name*='Captcha']",
                "input[id*='Captcha']",
                # Generic - look for text input in the same container as a captcha image
                "fieldset input[type='text']",
            ]

            for selector in input_selectors:
                try:
                    locator = page.locator(selector)
                    if await locator.count() > 0 and await locator.first.is_visible():
                        await locator.first.fill(answer)
                        logger.info(f"Filled CAPTCHA answer '{answer}' using selector: {selector}")
                        return
                except PlaywrightError:
                    continue

            # Fallback: look for any visible text input that's near/after an image
            try:
                inputs = page.locator("input[type='text']:visible")
                count = await inputs.count()
                for i in range(count):
                    input_elem = inputs.nth(i)
                    # Check if the input is empty (not prefilled)
                    current_value = await input_elem.input_value()
                    if not current_value or current_value.strip() == "":
                        await input_elem.fill(answer)
                        logger.info(f"Filled CAPTCHA answer '{answer}' using fallback input")
                        return
            except PlaywrightError:
                pass

            logger.warning("Could not find CAPTCHA input field")
        except PlaywrightError as e:
            logger.warning(f"Failed to fill CAPTCHA input: {e}")


# Global service instance (lazy initialization)
_captcha_service: Optional[CaptchaSolverService] = None


def get_captcha_service() -> CaptchaSolverService:
    """Get the global CAPTCHA solver service instance."""
    global _captcha_service
    if _captcha_service is None:
        _captcha_service = CaptchaSolverService()
    return _captcha_service
