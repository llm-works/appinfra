# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/builder/middleware.py.

Tests key functionality including:
- MiddlewareBuilder class and fluent API
- BuiltMiddleware execution and conditions
- LoggingMiddleware and CORSMiddleware
- Factory functions for middleware creation
"""

from unittest.mock import Mock

import pytest

from appinfra.app.builder.middleware import (
    BuiltMiddleware,
    CORSMiddleware,
    LoggingMiddleware,
    MiddlewareBuilder,
    create_cors_middleware,
    create_logging_middleware,
)

# =============================================================================
# Test MiddlewareBuilder Initialization
# =============================================================================


@pytest.mark.unit
class TestMiddlewareBuilderInit:
    """Test MiddlewareBuilder initialization (lines 16-28)."""

    def test_basic_initialization(self):
        """Test basic initialization (lines 23-28)."""
        builder = MiddlewareBuilder("test")

        assert builder._name == "test"
        assert builder._request_processor is None
        assert builder._response_processor is None
        assert builder._error_handler is None
        assert builder._conditions == []
        assert builder._priority == 0


# =============================================================================
# Test MiddlewareBuilder Methods
# =============================================================================


@pytest.mark.unit
class TestMiddlewareBuilderMethods:
    """Test MiddlewareBuilder builder methods."""

    def test_process_request(self):
        """Test process_request sets function (lines 30-39)."""
        builder = MiddlewareBuilder("test")
        func = Mock()

        result = builder.process_request(func)

        assert builder._request_processor is func
        assert result is builder

    def test_process_response(self):
        """Test process_response sets function (lines 41-50)."""
        builder = MiddlewareBuilder("test")
        func = Mock()

        result = builder.process_response(func)

        assert builder._response_processor is func
        assert result is builder

    def test_handle_error(self):
        """Test handle_error sets function (lines 52-61)."""
        builder = MiddlewareBuilder("test")
        func = Mock()

        result = builder.handle_error(func)

        assert builder._error_handler is func
        assert result is builder

    def test_when_adds_condition(self):
        """Test when adds condition (lines 63-72)."""
        builder = MiddlewareBuilder("test")
        condition = Mock()

        result = builder.when(condition)

        assert condition in builder._conditions
        assert result is builder

    def test_when_adds_multiple_conditions(self):
        """Test when can add multiple conditions."""
        builder = MiddlewareBuilder("test")
        cond1 = Mock()
        cond2 = Mock()

        builder.when(cond1).when(cond2)

        assert builder._conditions == [cond1, cond2]

    def test_with_priority(self):
        """Test with_priority sets priority (lines 74-82)."""
        builder = MiddlewareBuilder("test")

        result = builder.with_priority(10)

        assert builder._priority == 10
        assert result is builder


# =============================================================================
# Test MiddlewareBuilder build
# =============================================================================


@pytest.mark.unit
class TestMiddlewareBuilderBuild:
    """Test MiddlewareBuilder build method (lines 84-93)."""

    def test_build_creates_built_middleware(self):
        """Test build creates BuiltMiddleware instance (lines 86-93)."""
        builder = MiddlewareBuilder("test")

        result = builder.build()

        assert isinstance(result, BuiltMiddleware)
        assert result.name == "test"

    def test_build_passes_all_config(self):
        """Test build passes all configuration."""
        req_proc = Mock()
        resp_proc = Mock()
        err_handler = Mock()
        condition = Mock()

        builder = (
            MiddlewareBuilder("test")
            .process_request(req_proc)
            .process_response(resp_proc)
            .handle_error(err_handler)
            .when(condition)
            .with_priority(5)
        )

        result = builder.build()

        assert result._request_processor is req_proc
        assert result._response_processor is resp_proc
        assert result._error_handler is err_handler
        assert condition in result._conditions
        assert result._priority == 5


# =============================================================================
# Test BuiltMiddleware Initialization
# =============================================================================


@pytest.mark.unit
class TestBuiltMiddlewareInit:
    """Test BuiltMiddleware initialization (lines 99-125)."""

    def test_basic_initialization(self):
        """Test basic initialization (lines 119-125)."""
        mw = BuiltMiddleware("test")

        assert mw.name == "test"
        assert mw._request_processor is None
        assert mw._response_processor is None
        assert mw._error_handler is None
        assert mw._conditions == []
        assert mw._priority == 0

    def test_initialization_with_all_params(self):
        """Test initialization with all parameters."""
        req_proc = Mock()
        resp_proc = Mock()
        err_handler = Mock()
        conditions = [Mock(), Mock()]

        mw = BuiltMiddleware(
            name="test",
            request_processor=req_proc,
            response_processor=resp_proc,
            error_handler=err_handler,
            conditions=conditions,
            priority=10,
        )

        assert mw._request_processor is req_proc
        assert mw._response_processor is resp_proc
        assert mw._error_handler is err_handler
        assert mw._conditions == conditions
        assert mw._priority == 10


# =============================================================================
# Test BuiltMiddleware process_request
# =============================================================================


@pytest.mark.unit
class TestBuiltMiddlewareProcessRequest:
    """Test BuiltMiddleware process_request method (lines 127-142)."""

    @pytest.mark.asyncio
    async def test_returns_request_when_no_processor(self):
        """Test returns request unchanged when no processor (line 142)."""
        mw = BuiltMiddleware("test")
        request = Mock()

        result = await mw.process_request(request)

        assert result is request

    @pytest.mark.asyncio
    async def test_processes_request_with_processor(self):
        """Test processes request with processor (lines 134-136)."""
        processor = Mock(return_value="modified_request")
        mw = BuiltMiddleware("test", request_processor=processor)
        request = Mock()

        result = await mw.process_request(request)

        processor.assert_called_once_with(request)
        assert result == "modified_request"

    @pytest.mark.asyncio
    async def test_skips_when_condition_false(self):
        """Test skips processing when condition returns False (lines 130-131)."""
        processor = Mock()
        condition = Mock(return_value=False)
        mw = BuiltMiddleware(
            "test", request_processor=processor, conditions=[condition]
        )
        request = Mock()

        result = await mw.process_request(request)

        processor.assert_not_called()
        assert result is request

    @pytest.mark.asyncio
    async def test_handles_error_with_handler(self):
        """Test handles error with error handler (lines 137-140)."""
        processor = Mock(side_effect=ValueError("test error"))
        error_handler = Mock(return_value="error_response")
        mw = BuiltMiddleware(
            "test", request_processor=processor, error_handler=error_handler
        )
        request = Mock()

        result = await mw.process_request(request)

        error_handler.assert_called_once()
        assert result == "error_response"

    @pytest.mark.asyncio
    async def test_raises_when_no_error_handler(self):
        """Test raises when no error handler (line 140)."""
        processor = Mock(side_effect=ValueError("test error"))
        mw = BuiltMiddleware("test", request_processor=processor)
        request = Mock()

        with pytest.raises(ValueError):
            await mw.process_request(request)


# =============================================================================
# Test BuiltMiddleware process_response
# =============================================================================


@pytest.mark.unit
class TestBuiltMiddlewareProcessResponse:
    """Test BuiltMiddleware process_response method (lines 144-155)."""

    @pytest.mark.asyncio
    async def test_returns_response_when_no_processor(self):
        """Test returns response unchanged when no processor (line 155)."""
        mw = BuiltMiddleware("test")
        response = Mock()

        result = await mw.process_response(response)

        assert result is response

    @pytest.mark.asyncio
    async def test_processes_response_with_processor(self):
        """Test processes response with processor (lines 147-149)."""
        processor = Mock(return_value="modified_response")
        mw = BuiltMiddleware("test", response_processor=processor)
        response = Mock()

        result = await mw.process_response(response)

        processor.assert_called_once_with(response)
        assert result == "modified_response"

    @pytest.mark.asyncio
    async def test_handles_error_with_handler(self):
        """Test handles error with error handler (lines 150-152)."""
        processor = Mock(side_effect=ValueError("test error"))
        error_handler = Mock(return_value="error_response")
        mw = BuiltMiddleware(
            "test", response_processor=processor, error_handler=error_handler
        )
        response = Mock()

        result = await mw.process_response(response)

        error_handler.assert_called_once()
        assert result == "error_response"


# =============================================================================
# Test BuiltMiddleware _should_run
# =============================================================================


@pytest.mark.unit
class TestBuiltMiddlewareShouldRun:
    """Test BuiltMiddleware _should_run method (lines 157-170)."""

    def test_returns_true_when_no_conditions(self):
        """Test returns True when no conditions (lines 159-160)."""
        mw = BuiltMiddleware("test")
        request = Mock()

        result = mw._should_run(request)

        assert result is True

    def test_returns_true_when_all_conditions_pass(self):
        """Test returns True when all conditions pass (line 170)."""
        cond1 = Mock(return_value=True)
        cond2 = Mock(return_value=True)
        mw = BuiltMiddleware("test", conditions=[cond1, cond2])
        request = Mock()

        result = mw._should_run(request)

        assert result is True
        cond1.assert_called_once_with(request)
        cond2.assert_called_once_with(request)

    def test_returns_false_when_condition_fails(self):
        """Test returns False when any condition fails (lines 164-165)."""
        cond1 = Mock(return_value=True)
        cond2 = Mock(return_value=False)
        mw = BuiltMiddleware("test", conditions=[cond1, cond2])
        request = Mock()

        result = mw._should_run(request)

        assert result is False

    def test_returns_false_when_condition_raises(self):
        """Test returns False when condition raises (lines 166-168)."""
        cond = Mock(side_effect=ValueError("error"))
        mw = BuiltMiddleware("test", conditions=[cond])
        request = Mock()

        result = mw._should_run(request)

        assert result is False


# =============================================================================
# Test BuiltMiddleware __lt__
# =============================================================================


@pytest.mark.unit
class TestBuiltMiddlewareLt:
    """Test BuiltMiddleware __lt__ method (lines 172-174)."""

    def test_higher_priority_sorts_first(self):
        """Test higher priority middleware sorts before lower (line 174)."""
        mw_low = BuiltMiddleware("low", priority=1)
        mw_high = BuiltMiddleware("high", priority=10)

        # Higher priority should be "less than" (comes first)
        assert mw_high < mw_low
        assert not (mw_low < mw_high)

    def test_sorts_correctly(self):
        """Test middleware sorts by priority correctly."""
        mw1 = BuiltMiddleware("first", priority=10)
        mw2 = BuiltMiddleware("second", priority=5)
        mw3 = BuiltMiddleware("third", priority=1)

        sorted_list = sorted([mw3, mw1, mw2])

        assert sorted_list == [mw1, mw2, mw3]


# =============================================================================
# Test LoggingMiddleware
# =============================================================================


@pytest.mark.unit
class TestLoggingMiddleware:
    """Test LoggingMiddleware class (lines 177-208)."""

    def test_initialization(self):
        """Test initialization (lines 180-194)."""
        logger = Mock()
        mw = LoggingMiddleware(logger, log_requests=True, log_responses=False)

        assert mw.logger is logger
        assert mw.log_requests is True
        assert mw.log_responses is False

    def test_initialization_defaults(self):
        """Test initialization defaults."""
        mw = LoggingMiddleware()

        assert mw.logger is None
        assert mw.log_requests is True
        assert mw.log_responses is False

    @pytest.mark.asyncio
    async def test_logs_request(self):
        """Test logs request (lines 196-202)."""
        logger = Mock()
        mw = LoggingMiddleware(logger, log_requests=True)
        request = Mock(method="GET", path="/api/test")

        result = await mw.process_request(request)

        logger.info.assert_called_once()
        assert "GET" in logger.info.call_args[0][0]
        assert "/api/test" in logger.info.call_args[0][0]
        assert result is request

    @pytest.mark.asyncio
    async def test_skips_request_logging_when_disabled(self):
        """Test skips request logging when disabled."""
        logger = Mock()
        mw = LoggingMiddleware(logger, log_requests=False)
        request = Mock()

        await mw.process_request(request)

        logger.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_response(self):
        """Test logs response (lines 204-208)."""
        logger = Mock()
        mw = LoggingMiddleware(logger, log_responses=True)
        response = Mock(status_code=200)

        result = await mw.process_response(response)

        logger.info.assert_called_once()
        assert "200" in logger.info.call_args[0][0]
        assert result is response

    @pytest.mark.asyncio
    async def test_skips_response_logging_when_disabled(self):
        """Test skips response logging when disabled."""
        logger = Mock()
        mw = LoggingMiddleware(logger, log_responses=False)
        response = Mock()

        await mw.process_response(response)

        logger.info.assert_not_called()


# =============================================================================
# Test CORSMiddleware
# =============================================================================


@pytest.mark.unit
class TestCORSMiddleware:
    """Test CORSMiddleware class (lines 211-245)."""

    def test_initialization(self):
        """Test initialization (lines 214-224)."""
        mw = CORSMiddleware(origins=["http://example.com"], allow_credentials=False)

        assert mw.origins == ["http://example.com"]
        assert mw.allow_credentials is False

    def test_initialization_defaults(self):
        """Test initialization defaults."""
        mw = CORSMiddleware()

        assert mw.origins == ["*"]
        assert mw.allow_credentials is True

    @pytest.mark.asyncio
    async def test_process_request_sets_cors_origins(self):
        """Test process_request sets cors_origins (lines 226-231)."""
        mw = CORSMiddleware(origins=["http://example.com"])
        request = Mock()
        request.cors_origins = None

        result = await mw.process_request(request)

        assert request.cors_origins == ["http://example.com"]
        assert result is request

    @pytest.mark.asyncio
    async def test_process_response_adds_headers(self):
        """Test process_response adds CORS headers (lines 233-245)."""
        mw = CORSMiddleware(origins=["http://example.com"])
        response = Mock()
        response.headers = {}

        result = await mw.process_response(response)

        assert "Access-Control-Allow-Origin" in response.headers
        assert "Access-Control-Allow-Methods" in response.headers
        assert "Access-Control-Allow-Headers" in response.headers
        assert "Access-Control-Allow-Credentials" in response.headers
        assert result is response

    @pytest.mark.asyncio
    async def test_process_response_skips_credentials_when_disabled(self):
        """Test process_response skips credentials when disabled."""
        mw = CORSMiddleware(allow_credentials=False)
        response = Mock()
        response.headers = {}

        await mw.process_response(response)

        assert "Access-Control-Allow-Credentials" not in response.headers

    @pytest.mark.asyncio
    async def test_process_response_skips_without_headers(self):
        """Test process_response skips when no headers attribute."""
        mw = CORSMiddleware()
        response = Mock(spec=[])  # No headers attribute

        result = await mw.process_response(response)

        assert result is response


# =============================================================================
# Test Factory Functions
# =============================================================================


@pytest.mark.unit
class TestFactoryFunctions:
    """Test middleware factory functions."""

    def test_create_logging_middleware(self):
        """Test create_logging_middleware (lines 248-254)."""
        logger = Mock()
        builder = create_logging_middleware(logger, log_requests=True)

        assert isinstance(builder, MiddlewareBuilder)
        assert builder._name == "logging"
        assert builder._request_processor is not None
        assert builder._response_processor is not None

    def test_create_cors_middleware(self):
        """Test create_cors_middleware (lines 257-263)."""
        builder = create_cors_middleware(origins=["http://example.com"])

        assert isinstance(builder, MiddlewareBuilder)
        assert builder._name == "cors"
        assert builder._request_processor is not None
        assert builder._response_processor is not None


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestMiddlewareIntegration:
    """Test middleware integration scenarios."""

    @pytest.mark.asyncio
    async def test_full_middleware_pipeline(self):
        """Test complete middleware pipeline."""
        # Build middleware
        middleware = (
            MiddlewareBuilder("transform")
            .process_request(
                lambda req: Mock(method="POST", path=req.path, modified=True)
            )
            .process_response(
                lambda resp: {"status": resp["status"], "transformed": True}
            )
            .with_priority(10)
            .build()
        )

        # Process request
        request = Mock(method="GET", path="/api/test")
        processed_request = await middleware.process_request(request)
        assert processed_request.modified is True
        assert processed_request.method == "POST"

        # Process response
        response = {"status": 200}
        processed_response = await middleware.process_response(response)
        assert processed_response["transformed"] is True

    @pytest.mark.asyncio
    async def test_conditional_middleware(self):
        """Test middleware with conditions."""

        # Only process API requests
        def is_api_request(req):
            return req.path.startswith("/api/")

        middleware = (
            MiddlewareBuilder("api_only")
            .when(is_api_request)
            .process_request(lambda req: Mock(path=req.path, api=True))
            .build()
        )

        # API request should be processed
        api_request = Mock(path="/api/users")
        result = await middleware.process_request(api_request)
        assert result.api is True

        # Non-API request should pass through
        other_request = Mock(path="/static/file.js")
        result = await middleware.process_request(other_request)
        assert result is other_request

    @pytest.mark.asyncio
    async def test_error_handling_middleware(self):
        """Test middleware with error handling."""

        def failing_processor(req):
            raise ValueError("Processing failed")

        def error_handler(error, req):
            return Mock(error=str(error), original_path=req.path)

        middleware = (
            MiddlewareBuilder("with_error_handling")
            .process_request(failing_processor)
            .handle_error(error_handler)
            .build()
        )

        request = Mock(path="/api/test")
        result = await middleware.process_request(request)

        assert "Processing failed" in result.error
        assert result.original_path == "/api/test"

    def test_middleware_sorting(self):
        """Test middleware sorts by priority."""
        mw1 = MiddlewareBuilder("first").with_priority(1).build()
        mw2 = MiddlewareBuilder("second").with_priority(100).build()
        mw3 = MiddlewareBuilder("third").with_priority(50).build()

        sorted_mw = sorted([mw1, mw2, mw3])

        assert sorted_mw[0].name == "second"  # Highest priority
        assert sorted_mw[1].name == "third"
        assert sorted_mw[2].name == "first"  # Lowest priority
