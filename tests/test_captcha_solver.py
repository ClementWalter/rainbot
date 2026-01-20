"""Tests for the CAPTCHA solver service."""

from unittest.mock import MagicMock, patch

import pytest

from src.services.captcha_solver import (
    CaptchaSolveResult,
    CaptchaSolverService,
    get_captcha_service,
)


@pytest.fixture
def mock_solver():
    """Create a mock TwoCaptcha solver."""
    solver = MagicMock()
    return solver


@pytest.fixture
def service():
    """Create a CaptchaSolverService with a test API key."""
    return CaptchaSolverService(api_key="test-api-key")


@pytest.fixture
def mock_driver():
    """Create a mock WebDriver."""
    driver = MagicMock()
    driver.current_url = "https://tennis.paris.fr/booking"
    driver.page_source = ""
    return driver


class TestCaptchaSolveResult:
    """Tests for CaptchaSolveResult dataclass."""

    def test_successful_result(self):
        """Test successful CaptchaSolveResult."""
        result = CaptchaSolveResult(success=True, token="test-token")
        assert result.success is True
        assert result.token == "test-token"
        assert result.error_message is None

    def test_failed_result(self):
        """Test failed CaptchaSolveResult."""
        result = CaptchaSolveResult(success=False, error_message="Timeout")
        assert result.success is False
        assert result.token is None
        assert result.error_message == "Timeout"

    def test_result_default_values(self):
        """Test CaptchaSolveResult default values."""
        result = CaptchaSolveResult(success=True)
        assert result.success is True
        assert result.token is None
        assert result.error_message is None


class TestCaptchaSolverService:
    """Tests for CaptchaSolverService."""

    def test_service_initialization_with_api_key(self):
        """Test service initializes with API key."""
        service = CaptchaSolverService(api_key="my-api-key")
        assert service._api_key == "my-api-key"
        assert service._solver is None

    def test_service_initialization_without_api_key(self):
        """Test service initializes without API key (uses settings)."""
        with patch("src.services.captcha_solver.settings") as mock_settings:
            mock_settings.captcha.api_key = "settings-api-key"
            service = CaptchaSolverService()
            assert service._api_key == "settings-api-key"

    def test_solver_property_creates_instance(self, service):
        """Test solver property creates TwoCaptcha instance."""
        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance

            solver = service.solver

            mock_class.assert_called_once_with(
                apiKey="test-api-key",
                defaultTimeout=120,
                recaptchaTimeout=180,
                pollingInterval=5,
            )
            assert solver == mock_instance

    def test_solver_property_returns_same_instance(self, service):
        """Test solver property returns same instance on repeated calls."""
        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance

            solver1 = service.solver
            solver2 = service.solver

            # Should only create once
            mock_class.assert_called_once()
            assert solver1 is solver2

    def test_solver_without_api_key_raises(self):
        """Test solver raises when no API key configured."""
        with patch("src.services.captcha_solver.settings") as mock_settings:
            mock_settings.captcha.api_key = ""
            service = CaptchaSolverService(api_key=None)
            with pytest.raises(ValueError, match="CAPTCHA API key not configured"):
                _ = service.solver

    def test_get_balance_success(self, service):
        """Test getting account balance."""
        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_solver = MagicMock()
            mock_solver.balance.return_value = "5.50"
            mock_class.return_value = mock_solver

            balance = service.get_balance()

            assert balance == 5.50

    def test_solve_recaptcha_v2_success(self, service):
        """Test solving reCAPTCHA v2 successfully."""
        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_solver = MagicMock()
            mock_solver.recaptcha.return_value = {"code": "solved-token-v2"}
            mock_class.return_value = mock_solver

            result = service.solve_recaptcha_v2(
                sitekey="6Le-test-sitekey",
                url="https://test.com/page",
            )

            assert result.success is True
            assert result.token == "solved-token-v2"
            mock_solver.recaptcha.assert_called_once_with(
                sitekey="6Le-test-sitekey",
                url="https://test.com/page",
                invisible=False,
            )

    def test_solve_recaptcha_v2_timeout(self, service):
        """Test reCAPTCHA v2 timeout handling."""
        from twocaptcha.solver import TimeoutException

        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_solver = MagicMock()
            mock_solver.recaptcha.side_effect = TimeoutException()
            mock_class.return_value = mock_solver

            result = service.solve_recaptcha_v2(
                sitekey="test",
                url="https://test.com",
            )

            assert result.success is False
            assert "timed out" in result.error_message

    def test_solve_recaptcha_v2_api_error(self, service):
        """Test reCAPTCHA v2 API error handling."""
        from twocaptcha.api import ApiException

        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_solver = MagicMock()
            mock_solver.recaptcha.side_effect = ApiException("Invalid API key")
            mock_class.return_value = mock_solver

            result = service.solve_recaptcha_v2(
                sitekey="test",
                url="https://test.com",
            )

            assert result.success is False
            assert "Invalid API key" in result.error_message

    def test_solve_recaptcha_v3_success(self, service):
        """Test solving reCAPTCHA v3 successfully."""
        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_solver = MagicMock()
            mock_solver.recaptcha.return_value = {"code": "solved-token-v3"}
            mock_class.return_value = mock_solver

            result = service.solve_recaptcha_v3(
                sitekey="6Le-test-sitekey",
                url="https://test.com/page",
                action="submit",
                min_score=0.5,
            )

            assert result.success is True
            assert result.token == "solved-token-v3"
            mock_solver.recaptcha.assert_called_once_with(
                sitekey="6Le-test-sitekey",
                url="https://test.com/page",
                version="v3",
                action="submit",
                score=0.5,
            )

    def test_solve_image_captcha_success(self, service):
        """Test solving image CAPTCHA successfully."""
        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_solver = MagicMock()
            mock_solver.normal.return_value = {"code": "ABC123"}
            mock_class.return_value = mock_solver

            result = service.solve_image_captcha(
                image_path="/path/to/captcha.jpg",
                case_sensitive=True,
                numeric=0,
                min_length=5,
                max_length=8,
            )

            assert result.success is True
            assert result.token == "ABC123"
            mock_solver.normal.assert_called_once()

    def test_solve_image_captcha_network_error(self, service):
        """Test image CAPTCHA network error handling."""
        from twocaptcha.api import NetworkException

        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_solver = MagicMock()
            mock_solver.normal.side_effect = NetworkException("Connection failed")
            mock_class.return_value = mock_solver

            result = service.solve_image_captcha("/path/to/captcha.jpg")

            assert result.success is False
            assert "Network error" in result.error_message


class TestSolveCaptchaFromPage:
    """Tests for solve_captcha_from_page method."""

    def test_liveidentity_captcha_detected_and_solved(self, service, mock_driver):
        """Test LiveIdentity CAPTCHA detection and solving."""
        html = (
            'LI_ANTIBOT.loadAntibot(["IMAGE","AUDIO","FR","+KEY",'
            '"https://captcha.liveidentity.com/captcha",null,null,'
            '"antibot-id","request-id",true]);'
        )
        mock_driver.page_source = html

        mock_driver.find_element.return_value = MagicMock()

        with patch.object(service, "_solve_liveidentity_antibot") as mock_solver:
            mock_solver.return_value = CaptchaSolveResult(success=True, token="live-token")

            result = service.solve_captcha_from_page(mock_driver, max_retries=1)

        assert result.success is True
        assert result.token == "live-token"
        mock_driver.execute_script.assert_called_once()

    def test_no_captcha_detected(self, service, mock_driver):
        """Test when no CAPTCHA is present on page."""
        from selenium.common.exceptions import NoSuchElementException

        mock_driver.find_element.side_effect = NoSuchElementException()

        with patch("src.services.captcha_solver.TwoCaptcha"):
            result = service.solve_captcha_from_page(mock_driver)

            assert result.success is True
            assert "No CAPTCHA detected" in result.error_message

    def test_recaptcha_detected_and_solved(self, service, mock_driver):
        """Test reCAPTCHA detection and solving."""
        from selenium.common.exceptions import NoSuchElementException

        mock_recaptcha_element = MagicMock()
        mock_recaptcha_element.get_attribute.return_value = "test-sitekey"

        def find_element_side_effect(by, value):
            if "recaptcha" in value or "sitekey" in value or "g-recaptcha" in value:
                return mock_recaptcha_element
            raise NoSuchElementException()

        mock_driver.find_element.side_effect = find_element_side_effect

        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_solver = MagicMock()
            mock_solver.recaptcha.return_value = {"code": "solved-token"}
            mock_class.return_value = mock_solver

            result = service.solve_captcha_from_page(mock_driver)

            assert result.success is True
            assert result.token == "solved-token"

    def test_captcha_solving_max_retries(self, service, mock_driver):
        """Test CAPTCHA solving respects max retries."""
        from selenium.common.exceptions import NoSuchElementException
        from twocaptcha.api import ApiException

        mock_recaptcha_element = MagicMock()
        mock_recaptcha_element.get_attribute.return_value = "test-sitekey"

        def find_element_side_effect(by, value):
            if "recaptcha" in value or "sitekey" in value or "g-recaptcha" in value:
                return mock_recaptcha_element
            raise NoSuchElementException()

        mock_driver.find_element.side_effect = find_element_side_effect

        with patch("src.services.captcha_solver.TwoCaptcha") as mock_class:
            mock_solver = MagicMock()
            mock_solver.recaptcha.side_effect = ApiException("Solving failed")
            mock_class.return_value = mock_solver

            with patch("src.services.captcha_solver.time.sleep"):
                result = service.solve_captcha_from_page(mock_driver, max_retries=2)

            assert result.success is False
            assert "after 2 attempts" in result.error_message

    def test_recaptcha_invisible_uses_v2(self, service, mock_driver):
        """Test invisible reCAPTCHA uses v2 flow with invisible flag."""
        from selenium.common.exceptions import NoSuchElementException

        mock_recaptcha_element = MagicMock()

        def get_attribute_side_effect(attr):
            if attr == "data-sitekey":
                return "test-sitekey"
            if attr == "data-size":
                return "invisible"
            if attr == "data-action":
                return None
            return None

        mock_recaptcha_element.get_attribute.side_effect = get_attribute_side_effect

        def find_element_side_effect(by, value):
            if "recaptcha" in value or "sitekey" in value or "g-recaptcha" in value:
                return mock_recaptcha_element
            raise NoSuchElementException()

        mock_driver.find_element.side_effect = find_element_side_effect

        with patch.object(service, "solve_recaptcha_v2") as mock_v2, patch.object(
            service, "solve_recaptcha_v3"
        ) as mock_v3, patch.object(service, "_inject_recaptcha_token") as mock_inject:
            mock_v2.return_value = CaptchaSolveResult(success=True, token="v2-token")

            result = service.solve_captcha_from_page(mock_driver)

        assert result.success is True
        mock_v2.assert_called_once_with(
            "test-sitekey",
            mock_driver.current_url,
            invisible=True,
        )
        mock_v3.assert_not_called()
        mock_inject.assert_called_once_with(mock_driver, "v2-token")

    def test_recaptcha_v3_uses_action(self, service, mock_driver):
        """Test reCAPTCHA v3 uses action when available."""
        from selenium.common.exceptions import NoSuchElementException

        mock_recaptcha_element = MagicMock()

        def get_attribute_side_effect(attr):
            if attr == "data-sitekey":
                return "test-sitekey"
            if attr == "data-size":
                return ""
            if attr == "data-action":
                return "signup"
            return None

        mock_recaptcha_element.get_attribute.side_effect = get_attribute_side_effect

        def find_element_side_effect(by, value):
            if "recaptcha" in value or "sitekey" in value or "g-recaptcha" in value:
                return mock_recaptcha_element
            raise NoSuchElementException()

        mock_driver.find_element.side_effect = find_element_side_effect

        with patch.object(service, "solve_recaptcha_v2") as mock_v2, patch.object(
            service, "solve_recaptcha_v3"
        ) as mock_v3, patch.object(service, "_inject_recaptcha_token") as mock_inject:
            mock_v3.return_value = CaptchaSolveResult(success=True, token="v3-token")

            result = service.solve_captcha_from_page(mock_driver)

        assert result.success is True
        mock_v3.assert_called_once_with(
            "test-sitekey",
            mock_driver.current_url,
            action="signup",
        )
        mock_v2.assert_not_called()
        mock_inject.assert_called_once_with(mock_driver, "v3-token")


class TestLiveIdentityParsing:
    """Tests for LiveIdentity config parsing."""

    def test_parse_liveidentity_config(self, service):
        """Test parsing LiveIdentity config from page source."""
        html = (
            'LI_ANTIBOT.loadAntibot(["IMAGE","AUDIO","FR","+ACAhl8aUF&v",'
            '"https://captcha.liveidentity.com/captcha",null,null,'
            '"antibot-id","request-id",true]);'
        )

        config = service._parse_liveidentity_config(html)

        assert config is not None
        assert config.captcha_type == "IMAGE"
        assert config.locale == "FR"
        assert config.sp_key == "+ACAhl8aUF&v"
        assert config.base_url == "https://captcha.liveidentity.com/captcha"
        assert config.antibot_id == "antibot-id"
        assert config.request_id == "request-id"


class TestInjectRecaptchaToken:
    """Tests for _inject_recaptcha_token method."""

    def test_inject_token_success(self, service, mock_driver):
        """Test successful token injection."""
        service._inject_recaptcha_token(mock_driver, "test-token-123")

        mock_driver.execute_script.assert_called_once()
        call_args = mock_driver.execute_script.call_args[0][0]
        assert "test-token-123" in call_args

    def test_inject_token_webdriver_error(self, service, mock_driver):
        """Test token injection handles WebDriver errors."""
        from selenium.common.exceptions import WebDriverException

        mock_driver.execute_script.side_effect = WebDriverException("JS error")

        # Should not raise, just log warning
        service._inject_recaptcha_token(mock_driver, "test-token")

    def test_inject_token_with_special_characters(self, service, mock_driver):
        """Test token injection properly escapes special characters."""
        # Token with single quotes, double quotes, and backslashes
        token_with_quotes = "token'with\"special\\chars"
        service._inject_recaptcha_token(mock_driver, token_with_quotes)

        mock_driver.execute_script.assert_called_once()
        call_args = mock_driver.execute_script.call_args[0][0]
        # The token should be JSON-escaped (wrapped in double quotes with escapes)
        assert '"token\'with\\"special\\\\chars"' in call_args

    def test_inject_token_with_newlines(self, service, mock_driver):
        """Test token injection properly escapes newlines."""
        token_with_newline = "token\nwith\rnewlines"
        service._inject_recaptcha_token(mock_driver, token_with_newline)

        mock_driver.execute_script.assert_called_once()
        call_args = mock_driver.execute_script.call_args[0][0]
        # Newlines should be escaped as \n and \r in the JSON string
        assert "\\n" in call_args
        assert "\\r" in call_args


class TestGetCaptchaService:
    """Tests for get_captcha_service function."""

    def test_get_captcha_service_singleton(self):
        """Test get_captcha_service returns singleton instance."""
        # Reset global
        import src.services.captcha_solver as module

        module._captcha_service = None

        with patch.object(module.settings.captcha, "api_key", "test-key"):
            service1 = get_captcha_service()
            service2 = get_captcha_service()

            assert service1 is service2
