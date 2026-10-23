"""Registry and execution for acquisition hooks."""

from __future__ import annotations

from typing import Dict, Literal, Type

from newswitch.models.hooks import Hook, SoftwareAutofocusHook
from newswitch.protocols.hook_manager import HookContext, HookHandler, UnsupportedHook

#: Where in an acquisition hooks run: at the start, per timepoint, per position, per plane.
HookLevel = Literal["m", "t", "p", "z"]


class PythonHookManager:
    """Runs hooks with the handlers registered for their types.

    A hook without a handler is refused, not skipped: an acquisition asked for it. `check`
    refuses such hooks (and hooks that make no sense where they are asked for, like an
    autofocus inside a z stack) before an acquisition moves anything.
    """

    def __init__(self, context: HookContext) -> None:
        """A manager with no handlers yet, running them with `context`."""
        self._context = context
        self._hooks: Dict[str, HookHandler] = {}

    def register_hook(self, hook: Type[Hook], hook_handler: HookHandler) -> None:
        """Run `hook_handler` for hooks of type `hook`."""
        self._hooks[hook.__name__] = hook_handler

    def check(self, hooks: list[Hook], level: HookLevel) -> None:
        """Refuse hooks that cannot run, or not at `level`.

        Raises:
            UnsupportedHook: A hook has no handler, or is an autofocus inside a z stack
                (it would move the stack it is part of).
        """
        for hook in hooks:
            if type(hook).__name__ not in self._hooks:
                raise UnsupportedHook(f"{type(hook).__name__} cannot run on this microscope")
            if level == "z" and isinstance(hook, SoftwareAutofocusHook):
                raise UnsupportedHook("an autofocus cannot run per plane of a z stack")

    def execute(self, hook: Hook) -> None:
        """Run one hook.

        Raises:
            UnsupportedHook: It has no handler.
        """
        handler = self._hooks.get(type(hook).__name__)
        if handler is None:
            raise UnsupportedHook(f"{type(hook).__name__} cannot run on this microscope")
        handler(hook, self._context)

    def execute_all(self, hooks: list[Hook]) -> None:
        """Run hooks in order."""
        for hook in hooks:
            self.execute(hook)
