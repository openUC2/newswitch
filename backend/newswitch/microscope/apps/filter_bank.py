"""The filters."""

from typing import Tuple

from arkitekt import App

from newswitch.actions import filter_bank
from newswitch.microscope import locks
from newswitch.microscope.apps import core
from newswitch.microscope.run import Run
from newswitch.protocols.filter_bank import FilterBankManager
from newswitch.states.filter_bank import FilterBankState

app = App("newswitch", app_context=Run)
app.registry.merge(core.app.registry)

app.register_state(FilterBankState, required_locks=[locks.FILTER_BANK])
app.register_context(FilterBankManager, locks=[locks.FILTER_BANK])


async def provide_filter_bank(run: Run) -> Tuple[FilterBankManager, FilterBankState]:
    """The filters."""
    return run.microscope.filter_bank, run.microscope.filter_bank_state


app.register_startup(provide_filter_bank)
app.register_action(filter_bank.switch_filter)
app.register_action(filter_bank.toggle_filter)
