from copy import deepcopy

from structlog import configure
from structlog.stdlib import LoggerFactory, ProcessorFormatter
from structlog.contextvars import merge_contextvars
from structlog.dev import ConsoleRenderer
from structlog.processors import (
    JSONRenderer,
    format_exc_info,
    StackInfoRenderer,
    TimeStamper,
    add_log_level,
)
from logging import NullHandler, getLogger, INFO
from structlog.typing import EventDict

__all__ = ["setup_logging"]


def setup_logging(config, *args, **kwargs):
    def development_render(_, __, event_dict: EventDict) -> EventDict:
        if config.ENVIRONMENT == "DEV":
            console_dict = deepcopy(event_dict)
            console = ConsoleRenderer()
            print(console.__call__(_, __, console_dict))
        return event_dict

    configure(
        processors=[
            merge_contextvars,
            add_log_level,
            StackInfoRenderer(),
            TimeStamper(fmt="iso"),
            development_render,
            format_exc_info,
            ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    formatter = ProcessorFormatter(
        processors=[
            ProcessorFormatter.remove_processors_meta,
            JSONRenderer(),
        ]
    )

    handler = NullHandler()
    handler.setFormatter(formatter)

    root = getLogger()
    root.handlers.clear()
    root.setLevel(INFO)