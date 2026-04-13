"""Unit tests for AntiBotSolver without live network dependencies."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from paris_tennis_api.captcha import AntiBotSolver
from paris_tennis_api.exceptions import CaptchaError
from paris_tennis_api.models import AntiBotConfig


@dataclass
class _FakeResponse:
    """Minimal requests-like response object used to isolate solver behavior."""

    status_code: int
    payload: dict[str, object] | None = None
    content: bytes = b""

    def json(self) -> dict[str, object]:
        return self.payload or {}


def _config(method: str = "IMAGE") -> AntiBotConfig:
    """Build a reusable captcha config fixture with realistic defaults."""

    return AntiBotConfig(
        method=method,
        fallback_method="AUDIO",
        locale="FR",
        sp_key="sp-key",
        base_url="https://captcha.liveidentity.com/captcha",
        container_id="li-antibot",
        custom_css_url=None,
        antibot_id="antibot-id",
        request_id="request-id",
    )


def test_solve_returns_invisible_token_without_visible_fallback(monkeypatch) -> None:
    """Invisible challenge success should skip expensive image-solving logic."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        solver,
        "_create_transaction",
        lambda config, referer_url: {
            "antibotMethod": "INVISIBLE_CAPTCHA",
            "antibotId": "ab",
            "requestId": "rq",
        },
    )
    monkeypatch.setattr(
        solver,
        "_check_invisible",
        lambda transaction, config, referer_url: {"message": "ok-token", "code": "42"},
    )
    token = solver.solve(config=_config(), referer_url="https://tennis.paris.fr/page")
    assert token.token == "ok-token"


def test_solve_falls_back_to_visible_challenge_when_invisible_is_invalid(
    monkeypatch,
) -> None:
    """Invalid invisible answers should continue with visible challenge resolution."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        solver,
        "_create_transaction",
        lambda config, referer_url: {
            "antibotMethod": "INVISIBLE_CAPTCHA",
            "antibotId": "ab",
            "requestId": "rq",
        },
    )
    monkeypatch.setattr(
        solver,
        "_check_invisible",
        lambda transaction, config, referer_url: {
            "message": "Invalid response.",
            "requestId": "rq-2",
        },
    )
    monkeypatch.setattr(
        solver,
        "_solve_visible_challenge",
        lambda config, transaction, referer_url: "visible-token",
    )
    token = solver.solve(config=_config(), referer_url="https://tennis.paris.fr/page")
    assert token.token == "visible-token"


def test_create_transaction_raises_when_liveidentity_returns_error(monkeypatch) -> None:
    """Transaction creation failures must raise typed errors early."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(status_code=500),
    )
    with pytest.raises(CaptchaError):
        solver._create_transaction(config=_config(), referer_url="https://tennis.paris.fr")


def test_check_invisible_raises_when_http_request_fails(monkeypatch) -> None:
    """Invisible captcha check should fail hard on transport errors."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.get",
        lambda *args, **kwargs: _FakeResponse(status_code=502),
    )
    with pytest.raises(CaptchaError):
        solver._check_invisible(
            transaction={"antibotId": "ab", "requestId": "rq"},
            config=_config(),
            referer_url="https://tennis.paris.fr",
        )


def test_create_transaction_returns_payload_on_success(monkeypatch) -> None:
    """Successful transaction creation should return parsed JSON payload unchanged."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    payload = {"antibotId": "ab", "requestId": "rq"}
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(status_code=200, payload=payload),
    )
    response = solver._create_transaction(config=_config(), referer_url="https://tennis.paris.fr")
    assert response["requestId"] == "rq"


def test_check_invisible_returns_payload_on_success(monkeypatch) -> None:
    """Successful invisible-check call should surface provider payload to caller."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    payload = {"message": "ok"}
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.get",
        lambda *args, **kwargs: _FakeResponse(status_code=200, payload=payload),
    )
    response = solver._check_invisible(
        transaction={"antibotId": "ab", "requestId": "rq"},
        config=_config(),
        referer_url="https://tennis.paris.fr",
    )
    assert response["message"] == "ok"


def test_fetch_challenge_requires_questions_payload(monkeypatch) -> None:
    """Solver should reject empty challenge payloads as invalid responses."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(status_code=200, payload={"questions": []}),
    )
    with pytest.raises(CaptchaError):
        solver._fetch_challenge(
            config=_config(),
            transaction={"antibotId": "ab", "requestId": "rq"},
            referer_url="https://tennis.paris.fr",
        )


def test_fetch_challenge_raises_on_http_error(monkeypatch) -> None:
    """Transport failures should raise explicit challenge-fetch errors."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(status_code=503),
    )
    with pytest.raises(CaptchaError):
        solver._fetch_challenge(
            config=_config(),
            transaction={"antibotId": "ab", "requestId": "rq"},
            referer_url="https://tennis.paris.fr",
        )


def test_fetch_challenge_returns_payload_on_success(monkeypatch) -> None:
    """Valid challenge responses should be returned untouched for downstream solving."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    payload = {"questions": ["/q.png"], "captchaValidationUrl": "/validate"}
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(status_code=200, payload=payload),
    )
    challenge = solver._fetch_challenge(
        config=_config(),
        transaction={"antibotId": "ab", "requestId": "rq"},
        referer_url="https://tennis.paris.fr",
    )
    assert challenge["questions"] == ["/q.png"]


def test_solve_visible_challenge_rejects_unsupported_methods() -> None:
    """Only IMAGE challenge mode is implemented and should be enforced explicitly."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    with pytest.raises(CaptchaError):
        solver._solve_visible_challenge(
            config=_config(method="AUDIO"),
            transaction={"antibotId": "ab", "requestId": "rq"},
            referer_url="https://tennis.paris.fr",
        )


def test_solve_visible_challenge_returns_first_valid_token(monkeypatch) -> None:
    """Visible challenge loop should stop as soon as a non-empty valid token appears."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        solver,
        "_fetch_challenge",
        lambda config, transaction, referer_url: {
            "questions": ["/q.png"],
            "captchaValidationUrl": "/validate",
        },
    )
    monkeypatch.setattr(solver, "_solve_image_answer", lambda config, challenge, referer_url: "1234")
    tokens = iter(["Invalid response.", "visible-token"])
    monkeypatch.setattr(
        solver,
        "_validate_answer",
        lambda config, challenge, answer, referer_url: next(tokens),
    )
    token = solver._solve_visible_challenge(
        config=_config(),
        transaction={"antibotId": "ab", "requestId": "rq"},
        referer_url="https://tennis.paris.fr",
    )
    assert token == "visible-token"


def test_solve_visible_challenge_raises_after_retries(monkeypatch) -> None:
    """Visible challenge should raise after exhausting retries without valid token."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        solver,
        "_fetch_challenge",
        lambda config, transaction, referer_url: {
            "questions": ["/q.png"],
            "captchaValidationUrl": "/validate",
        },
    )
    monkeypatch.setattr(solver, "_solve_image_answer", lambda config, challenge, referer_url: "1234")
    monkeypatch.setattr(
        solver,
        "_validate_answer",
        lambda config, challenge, answer, referer_url: "",
    )
    with pytest.raises(CaptchaError):
        solver._solve_visible_challenge(
            config=_config(),
            transaction={"antibotId": "ab", "requestId": "rq"},
            referer_url="https://tennis.paris.fr",
        )


def test_solve_image_answer_returns_2captcha_result(monkeypatch) -> None:
    """Image challenge answers should surface the solved 2captcha response text."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")

    def _fake_get(url: str, *args, **kwargs) -> _FakeResponse:
        if "res.php" in url:
            return _FakeResponse(status_code=200, payload={"status": 1, "request": "abcd"})
        return _FakeResponse(status_code=200, content=b"img")

    monkeypatch.setattr("paris_tennis_api.captcha.requests.get", _fake_get)
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(
            status_code=200, payload={"status": 1, "request": "captcha-id"}
        ),
    )
    monkeypatch.setattr("paris_tennis_api.captcha.time.sleep", lambda *_: None)
    answer = solver._solve_image_answer(
        config=_config(),
        challenge={"questions": ["/q.png"]},
        referer_url="https://tennis.paris.fr",
    )
    assert answer == "abcd"


def test_solve_image_answer_raises_on_image_download_failure(monkeypatch) -> None:
    """Image download failures should stop solving immediately with typed error."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.get",
        lambda *args, **kwargs: _FakeResponse(status_code=404),
    )
    with pytest.raises(CaptchaError):
        solver._solve_image_answer(
            config=_config(),
            challenge={"questions": ["/q.png"]},
            referer_url="https://tennis.paris.fr",
        )


def test_solve_image_answer_raises_on_2captcha_submit_failure(monkeypatch) -> None:
    """2captcha submit errors should raise explicit failures before polling begins."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.get",
        lambda *args, **kwargs: _FakeResponse(status_code=200, content=b"img"),
    )
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(
            status_code=200, payload={"status": 0, "request": "bad-key"}
        ),
    )
    with pytest.raises(CaptchaError):
        solver._solve_image_answer(
            config=_config(),
            challenge={"questions": ["/q.png"]},
            referer_url="https://tennis.paris.fr",
        )


def test_solve_image_answer_raises_on_2captcha_poll_error(monkeypatch) -> None:
    """Polling responses other than NOT_READY should raise to avoid silent bad states."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")

    def _fake_get(url: str, *args, **kwargs) -> _FakeResponse:
        if "res.php" in url:
            return _FakeResponse(status_code=200, payload={"status": 0, "request": "ERROR"})
        return _FakeResponse(status_code=200, content=b"img")

    monkeypatch.setattr("paris_tennis_api.captcha.requests.get", _fake_get)
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(
            status_code=200, payload={"status": 1, "request": "captcha-id"}
        ),
    )
    monkeypatch.setattr("paris_tennis_api.captcha.time.sleep", lambda *_: None)
    with pytest.raises(CaptchaError):
        solver._solve_image_answer(
            config=_config(),
            challenge={"questions": ["/q.png"]},
            referer_url="https://tennis.paris.fr",
        )


def test_solve_image_answer_raises_on_poll_timeout(monkeypatch) -> None:
    """Repeated NOT_READY responses should eventually timeout with a typed error."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")

    def _fake_get(url: str, *args, **kwargs) -> _FakeResponse:
        if "res.php" in url:
            return _FakeResponse(
                status_code=200, payload={"status": 0, "request": "CAPCHA_NOT_READY"}
            )
        return _FakeResponse(status_code=200, content=b"img")

    monkeypatch.setattr("paris_tennis_api.captcha.requests.get", _fake_get)
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(
            status_code=200, payload={"status": 1, "request": "captcha-id"}
        ),
    )
    monkeypatch.setattr("paris_tennis_api.captcha.time.sleep", lambda *_: None)
    with pytest.raises(CaptchaError):
        solver._solve_image_answer(
            config=_config(),
            challenge={"questions": ["/q.png"]},
            referer_url="https://tennis.paris.fr",
        )


def test_validate_answer_returns_empty_on_http_error(monkeypatch) -> None:
    """Validation HTTP errors should not crash booking flow and must return empty token."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(status_code=500),
    )
    token = solver._validate_answer(
        config=_config(),
        challenge={"captchaValidationUrl": "/validate"},
        answer="1234",
        referer_url="https://tennis.paris.fr",
    )
    assert token == ""


def test_validate_answer_returns_message_token(monkeypatch) -> None:
    """Successful validation should return message token payload for form submission."""

    solver = AntiBotSolver(captcha_api_key="captcha-key")
    monkeypatch.setattr(
        "paris_tennis_api.captcha.requests.post",
        lambda *args, **kwargs: _FakeResponse(
            status_code=200, payload={"message": "token-from-message"}
        ),
    )
    token = solver._validate_answer(
        config=_config(),
        challenge={"captchaValidationUrl": "/validate"},
        answer="1234",
        referer_url="https://tennis.paris.fr",
    )
    assert token == "token-from-message"
def test_liveidentity_headers_include_expected_origin_fields() -> None:
    """Headers must mimic browser origin/referrer to pass LiveIdentity checks."""

    headers = AntiBotSolver._liveidentity_headers(
        config=_config(),
        referer_url="https://tennis.paris.fr/tennis/jsp/site/Portal.jsp",
    )
    assert headers["Origin"] == "https://tennis.paris.fr"
