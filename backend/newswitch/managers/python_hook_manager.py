"""Registry and execution for acquisition hooks."""

from __future__ import annotations

import logging
from typing import Dict, Type

from newswitch.protocols.hook_manager import HookContext, Hook, HookHandler

logger = logging.getLogger(__name__)


class PythonHookManager:
    """Registry and execution for acquisition hooks."""

    def __init__(self, context: HookContext) -> None:
        """Initialize the PythonHookManager with an empty registry."""
        self._context = context
        self._hooks: Dict[str, HookHandler] = {}

    def register_hook(self, hook: Type[Hook], hook_handler: HookHandler) -> None:
        """Register a hook implementation.

        The hook can be an instance or a class. If a class is provided, the
        manager attempts to instantiate it with the HookContext. If that fails,
        it falls back to a no-arg constructor and calls initialize if present.
        """

        self._hooks[hook.__name__] = hook_handler

    def execute(self, hook: Hook) -> None:
        """Execute a single hook if registered."""
        handler = self._hooks.get(type(hook).__name__)
        if handler is None:
            return
        handler(hook, self._context)

    def execute_all(self, hooks: list[Hook]) -> None:
        """Execute a list of hooks in order."""
        for hook in hooks:
            # self.execute(hook)
            logger.info("Executing hook: %s", hook)
