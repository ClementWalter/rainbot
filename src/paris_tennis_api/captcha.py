"""LiveIdentity captcha solver used during reservation confirmation."""

from __future__ import annotations

import base64
import logging
import time
from urllib.parse import urljoin

import requests

from paris_tennis_api.exceptions import CaptchaError
from paris_tennis_api.models import AntiBotConfig, AntiBotToken


class AntiBotSolver:
    """Resolve LI_ANTIBOT token required by reservation captcha form."""

    def __init__(
        self,
        captcha_api_key: str,
        logger: logging.Logger | None = None,
    ) -> None:
        self._captcha_api_key = captcha_api_key
        self._logger = logger or logging.getLogger(__name__)

    def solve(self, config: AntiBotConfig, referer_url: str) -> AntiBotToken:
        """Return token values ready to post back to reservation action."""

        transaction = self._create_transaction(config=config, referer_url=referer_url)
        if transaction.get("antibotMethod") == "INVISIBLE_CAPTCHA":
            invisible = self._check_invisible(
                transaction=transaction, config=config, referer_url=referer_url
            )
            token = invisible.get("message") or invisible.get("antibotToken")
            if token and token not in {"Invalid response.", "Blacklisted end-user."}:
                return AntiBotToken(
                    container_id=config.container_id,
                    token=token,
                    token_code=str(invisible.get("code", "")),
                )
            # We fall through to visible challenge when invisible check asks for it.
            if invisible.get("requestId"):
                transaction["requestId"] = invisible["requestId"]

        token = self._solve_visible_challenge(
            config=config,
            transaction=transaction,
            referer_url=referer_url,
        )
        return AntiBotToken(
            container_id=config.container_id,
            token=token,
            token_code="",
        )

    def _create_transaction(self, config: AntiBotConfig, referer_url: str) -> dict:
        params: dict[str, str] = {}
        if config.antibot_id:
            params["antibotId"] = config.antibot_id
        if config.request_id:
            params["requestId"] = config.request_id

        response = requests.post(
            f"{config.base_url}/public/frontend/api/v3/captchas/transaction",
            params=params,
            headers=self._liveidentity_headers(config=config, referer_url=referer_url),
            timeout=30,
        )
        if response.status_code >= 400:
            raise CaptchaError(
                f"Failed to create captcha transaction (status {response.status_code})."
            )
        return response.json()

    def _check_invisible(
        self, transaction: dict, config: AntiBotConfig, referer_url: str
    ) -> dict:
        response = requests.get(
            (
                f"{config.base_url}/public/frontend/api/v3/captchas/"
                f"checkInvisibleCaptcha/{transaction['antibotId']}/{transaction['requestId']}"
            ),
            headers=self._liveidentity_headers(config=config, referer_url=referer_url),
            timeout=30,
        )
        if response.status_code >= 400:
            raise CaptchaError(
                f"Invisible captcha check failed (status {response.status_code})."
            )
        return response.json()

    def _solve_visible_challenge(
        self, config: AntiBotConfig, transaction: dict, referer_url: str
    ) -> str:
        if config.method != "IMAGE":
            raise CaptchaError(f"Unsupported visible captcha method '{config.method}'.")

        for _ in range(6):
            challenge = self._fetch_challenge(
                config=config,
                transaction=transaction,
                referer_url=referer_url,
            )
            answer = self._solve_image_answer(
                config=config,
                challenge=challenge,
                referer_url=referer_url,
            )
            token = self._validate_answer(
                config=config,
                challenge=challenge,
                answer=answer,
                referer_url=referer_url,
            )
            if token and token not in {"Invalid response.", "Blacklisted end-user."}:
                return token

        raise CaptchaError("Could not solve visible captcha after multiple attempts.")

    def _fetch_challenge(
        self, config: AntiBotConfig, transaction: dict, referer_url: str
    ) -> dict:
        headers = self._liveidentity_headers(config=config, referer_url=referer_url)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["X-LI-request-id"] = str(transaction["requestId"])
        headers["X-LI-antibot-id"] = str(transaction["antibotId"])

        response = requests.post(
            f"{config.base_url}/public/frontend/api/v3/captchas",
            headers=headers,
            data={"type": config.method, "locale": config.locale},
            timeout=30,
        )
        if response.status_code >= 400:
            raise CaptchaError(
                f"Failed to fetch captcha challenge (status {response.status_code})."
            )

        payload = response.json()
        if not payload.get("questions"):
            raise CaptchaError("Captcha challenge has no questions.")
        return payload

    def _solve_image_answer(
        self, config: AntiBotConfig, challenge: dict, referer_url: str
    ) -> str:
        image_url = urljoin(
            config.base_url + "/", challenge["questions"][0].lstrip("/")
        )
        image_response = requests.get(
            image_url,
            headers={"Origin": "https://tennis.paris.fr", "Referer": referer_url},
            timeout=30,
        )
        if image_response.status_code >= 400:
            raise CaptchaError(
                f"Failed to download captcha image (status {image_response.status_code})."
            )

        encoded = base64.b64encode(image_response.content).decode("ascii")
        submit = requests.post(
            "https://2captcha.com/in.php",
            data={
                "key": self._captcha_api_key,
                "method": "base64",
                "body": encoded,
                "json": 1,
                "lang": "fr",
            },
            timeout=30,
        )
        submit_payload = submit.json()
        if submit_payload.get("status") != 1:
            raise CaptchaError(f"2captcha submission failed: {submit_payload}.")

        captcha_id = submit_payload["request"]
        for _ in range(24):
            time.sleep(5)
            poll = requests.get(
                "https://2captcha.com/res.php",
                params={
                    "key": self._captcha_api_key,
                    "action": "get",
                    "id": captcha_id,
                    "json": 1,
                },
                timeout=30,
            )
            poll_payload = poll.json()
            if poll_payload.get("status") == 1:
                return str(poll_payload["request"]).strip()
            if poll_payload.get("request") != "CAPCHA_NOT_READY":
                raise CaptchaError(f"2captcha polling failed: {poll_payload}.")

        raise CaptchaError("2captcha timed out while solving image captcha.")

    def _validate_answer(
        self,
        config: AntiBotConfig,
        challenge: dict,
        answer: str,
        referer_url: str,
    ) -> str:
        validation_url = urljoin(
            config.base_url + "/",
            str(challenge["captchaValidationUrl"]).lstrip("/"),
        )
        headers = self._liveidentity_headers(config=config, referer_url=referer_url)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        response = requests.post(
            validation_url,
            headers=headers,
            data={"answer": answer},
            timeout=30,
        )
        if response.status_code >= 400:
            self._logger.warning(
                "Captcha validation returned HTTP %s", response.status_code
            )
            return ""
        payload = response.json()
        return str(payload.get("message") or payload.get("antibotToken") or "")

    @staticmethod
    def _liveidentity_headers(
        config: AntiBotConfig, referer_url: str
    ) -> dict[str, str]:
        """Mirror browser headers because LiveIdentity rejects non-browser origins."""

        return {
            "X-LI-sp-key": config.sp_key,
            "X-LI-js-version": "v4",
            "Origin": "https://tennis.paris.fr",
            "Referer": referer_url,
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
        }
