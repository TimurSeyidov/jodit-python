"""Request pipeline of one connector instance."""

import inspect
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from jcpy.acl import AccessControl
from jcpy.context import ActionContext, RequestContext
from jcpy.errors import HttpError
from jcpy.responses import error_response, internal_error_response
from jcpy.v1 import ACTIONS
from jcpy.v1.ping.handler import PingResponse

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jcpy.acl import AccessControlProtocol, RulesProvider
    from jcpy.config.models import AppConfig
    from jcpy.context import ActionHandler
    from jcpy.types import AuthCallback, OriginPredicate

logger = logging.getLogger("jcpy")

ONLY_POST_MESSAGE = "GET requests are disabled. Use POST instead."
CORS_ALLOWED_HEADERS = (
    "Origin,X-Requested-With,Content-Type,Accept,Authorization"
)
CORS_ALLOWED_METHODS = "GET, POST, OPTIONS"
ROUTE_METHODS = "GET, HEAD, POST"


class Connector:
    """One isolated connector instance: configuration, callbacks, routes.

    Args:
        config: Instance configuration.
        check_authentication: Resolves the user role per request;
            without it every request gets ``defaultRole``.
        allowed_origins: CORS origin predicate; replaces the
            ``allowedOrigins`` list of the configuration.
        access_control: Callable loading the access rules on every
            check; replaces the ``accessControl`` list of the
            configuration.
        access_control_instance: Custom access control implementation;
            replaces both rule sources above.
        actions: Action handlers by name.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        check_authentication: AuthCallback | None = None,
        allowed_origins: OriginPredicate | None = None,
        access_control: RulesProvider | None = None,
        access_control_instance: AccessControlProtocol | None = None,
        actions: Mapping[str, ActionHandler] = ACTIONS,
    ) -> None:
        self.config = config
        self.check_authentication = check_authentication
        self.allowed_origins = allowed_origins
        self.actions = actions
        self.access: AccessControlProtocol = (
            access_control_instance
            or AccessControl(access_control or config.access_control)
        )
        open_access = (
            not config.access_control
            and access_control is None
            and access_control_instance is None
        )
        if check_authentication is None and open_access:
            logger.warning(
                "No check_authentication callback and an empty "
                "accessControl: every client gets role %r with full "
                "access to all actions",
                config.default_role,
            )

    def build_router(self) -> APIRouter:
        """Create the routes of this instance.

        Returns:
            Router serving ``/ping``, ``/`` and ``/{action}``.
        """
        router = APIRouter()
        router.add_api_route(
            "/ping",
            self.ping,
            methods=["GET"],
            response_model=PingResponse,
            summary="Liveness probe",
        )
        for path in ("/", "/{action}"):
            router.add_api_route(
                path,
                self.dispatch,
                methods=["GET", "POST", "OPTIONS"],
                summary="Run a connector action",
            )
        return router

    async def ping(self, request: Request) -> Response:
        """Answer the liveness probe.

        Args:
            request: Incoming request.

        Returns:
            ``{"success": true}``, or ``405`` when only POST is allowed.
        """
        if self.config.only_post and request.method == "GET":
            return error_response(
                HTTPStatus.METHOD_NOT_ALLOWED, [ONLY_POST_MESSAGE]
            )
        return JSONResponse(PingResponse().model_dump())

    async def dispatch(self, request: Request) -> Response:
        """Serve a connector action.

        Order: POST-only guard, CORS, authentication, parameters,
        action handler. Every failure becomes an error envelope.

        Args:
            request: Incoming request.

        Returns:
            Action response or error envelope.
        """
        cors_headers: dict[str, str] = {}
        try:
            if self.config.only_post and request.method == "GET":
                raise HttpError.method_not_allowed(ONLY_POST_MESSAGE)
            cors_headers, early = await self._cors(request)
            if early is not None:
                return early
            role = await self._authenticate(request)
            params = await RequestContext.from_request(request)
            action = params.action
            await self.access.check_permission(role, action, params.path)
            handler = self.actions.get(action)
            if handler is None:
                raise HttpError.not_found(f'Action "{action}" not found')
            response = await handler(
                ActionContext(request, self.config, role, params, self.access)
            )
        except HttpError as error:
            self._log(error)
            response = error_response(error.status_code, error.messages)
        except Exception as error:
            self._log(error)
            response = internal_error_response(str(error))
        response.headers.update(cors_headers)
        return response

    def _log(self, error: Exception) -> None:
        if self.config.debug:
            logger.error("Request failed", exc_info=error)

    async def _authenticate(self, request: Request) -> str:
        if self.check_authentication is None:
            return self.config.default_role
        result = self.check_authentication(request)
        # Callbacks are user code: check the returned type at runtime.
        role: object = await result if inspect.isawaitable(result) else result
        if not isinstance(role, str):
            msg = "check_authentication must return the role as a string"
            raise TypeError(msg)
        return role

    async def _origin_allowed(self, origin: str, request: Request) -> bool:
        if self.allowed_origins is not None:
            allowed = self.allowed_origins(origin, request)
            if inspect.isawaitable(allowed):
                allowed = await allowed
            return bool(allowed)
        if self.config.allowed_origins is None:
            return True
        return origin in self.config.allowed_origins

    async def _cors(
        self, request: Request
    ) -> tuple[dict[str, str], Response | None]:
        preflight = request.method == "OPTIONS"
        if not self.config.allow_cross_origin:
            if preflight:
                return {}, PlainTextResponse(
                    ROUTE_METHODS, headers={"Allow": ROUTE_METHODS}
                )
            return {}, None

        origin = request.headers.get("origin", "")
        if origin and not await self._origin_allowed(origin, request):
            if preflight:
                return {}, PlainTextResponse(
                    "Forbidden", status_code=HTTPStatus.FORBIDDEN
                )
            return {}, None

        headers = {
            "Access-Control-Allow-Origin": origin or "*",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Headers": CORS_ALLOWED_HEADERS,
            "Access-Control-Max-Age": "86400",
        }
        if preflight:
            headers["Access-Control-Allow-Methods"] = CORS_ALLOWED_METHODS
            return headers, PlainTextResponse("OK", headers=headers)
        return headers, None
