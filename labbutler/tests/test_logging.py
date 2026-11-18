"""Production logging: server errors must reach stdout even with DEBUG off."""

import io
import logging

from django.conf import settings


def _console_handler() -> logging.StreamHandler:
    handlers = logging.getLogger("django").handlers
    return next(h for h in handlers if isinstance(h, logging.StreamHandler))


def test_request_errors_are_written_to_the_console_without_debug():
    assert settings.DEBUG is False  # the scenario that used to drop tracebacks
    handler = _console_handler()
    stream = io.StringIO()
    original = handler.setStream(stream)
    try:
        logging.getLogger("django.request").error("Internal Server Error: /boom/")
    finally:
        handler.setStream(original)
    assert "ERROR django.request: Internal Server Error: /boom/" in stream.getvalue()


def test_django_messages_are_not_duplicated_by_the_root_logger():
    assert logging.getLogger("django").propagate is False
