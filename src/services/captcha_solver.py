"""CAPTCHA solving service using 2Captcha API.

This module provides functionality to solve various types of CAPTCHAs
encountered on the Paris Tennis booking website.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

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


@dataclass
class CaptchaSolveResult:
    """Result of a CAPTCHA solving attempt."""

    success: bool
    token: Optional[str] = None
    error_message: Optional[str] = None


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
            return CaptchaSolveResult(
                success=False, error_message="CAPTCHA solving timed out"
            )
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
            return CaptchaSolveResult(
                success=False, error_message="CAPTCHA solving timed out"
            )
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

            result = self.solver.normal(image_path, **params)
            logger.info("Image CAPTCHA solved successfully")
            return CaptchaSolveResult(success=True, token=result["code"])
        except TimeoutException:
            logger.error("Image CAPTCHA solving timed out")
            return CaptchaSolveResult(
                success=False, error_message="CAPTCHA solving timed out"
            )
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

        for attempt in range(1, max_retries + 1):
            logger.info(f"CAPTCHA solve attempt {attempt}/{max_retries}")

            # Try to detect reCAPTCHA
            recaptcha_result = self._detect_and_solve_recaptcha(driver, current_url)
            if recaptcha_result is not None:
                if recaptcha_result.success:
                    return recaptcha_result
                # Continue to next attempt if failed
                time.sleep(2)
                continue

            # Try to detect image CAPTCHA
            image_result = self._detect_and_solve_image_captcha(driver)
            if image_result is not None:
                if image_result.success:
                    return image_result
                # Continue to next attempt if failed
                time.sleep(2)
                continue

            # No CAPTCHA detected
            logger.info("No CAPTCHA detected on page")
            return CaptchaSolveResult(
                success=True, error_message="No CAPTCHA detected"
            )

        return CaptchaSolveResult(
            success=False,
            error_message=f"Failed to solve CAPTCHA after {max_retries} attempts",
        )

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
            for selector in recaptcha_selectors:
                try:
                    element = driver.find_element(By.CSS_SELECTOR, selector)
                    sitekey = element.get_attribute("data-sitekey")
                    if not sitekey:
                        # Try to get from parent or iframe
                        parent = driver.find_element(By.CSS_SELECTOR, ".g-recaptcha")
                        sitekey = parent.get_attribute("data-sitekey")
                    if sitekey:
                        break
                except NoSuchElementException:
                    continue

            if not sitekey:
                return None

            # Detect if it's v3 by checking for score-related attributes
            is_v3 = False
            try:
                element = driver.find_element(By.CSS_SELECTOR, "[data-sitekey]")
                if element.get_attribute("data-size") == "invisible":
                    is_v3 = True
            except NoSuchElementException:
                pass

            if is_v3:
                result = self.solve_recaptcha_v3(sitekey, url)
            else:
                result = self.solve_recaptcha_v2(sitekey, url)

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
            driver.execute_script(
                f"""
                var token = {escaped_token};
                var textarea = document.getElementById('g-recaptcha-response');
                if (textarea) {{
                    textarea.innerHTML = token;
                    textarea.value = token;
                }}
                // Also try hidden input
                var hiddenInputs = document.querySelectorAll('input[name="g-recaptcha-response"]');
                hiddenInputs.forEach(function(input) {{
                    input.value = token;
                }});
                // Trigger callback if exists
                if (typeof ___grecaptcha_cfg !== 'undefined') {{
                    for (var key in ___grecaptcha_cfg.clients) {{
                        var client = ___grecaptcha_cfg.clients[key];
                        if (client && client.hl && client.hl.l) {{
                            client.hl.l.callback(token);
                        }}
                    }}
                }}
                """
            )
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

            # Solve the image CAPTCHA
            result = self.solve_image_captcha(img_src)

            if result.success and result.token:
                # Find and fill the input field
                self._fill_captcha_input(driver, result.token)

            return result

        except WebDriverException as e:
            logger.error(f"WebDriver error detecting image CAPTCHA: {e}")
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
