"""The UI the backend declares: the newswitch blok catalog and the bloks built in it.

`declare_ui` declares the catalog, the bloks every setup has (``jonda``), and the one UI
`ImswitchConfig.ui` chooses as the default blok: ``standard``, ``minimal`` or ``design``
(a microscope described by an optikit design, see `newswitch.bloks.design`). Only that one
is declared.

`nsapp` is one per process, so the UI is declared once: `create_app` calls this before
serving, and a second call with the same choice does nothing.
"""

from newswitch.bloks.catalog import CATALOG_FILE, CATALOG_NAME, declare_catalog
from newswitch.config import ImswitchConfig

__all__ = ["CATALOG_FILE", "CATALOG_NAME", "declare_ui"]

_declared: tuple[str, str | None] | None = None


def declare_ui(config: ImswitchConfig) -> None:
    """Declare the catalog and the UI `config` chooses.

    Raises:
        RuntimeError: A different UI was already declared in this process.
    """
    global _declared
    choice = (config.ui, str(config.design) if config.ui == "design" else None)
    if _declared is not None:
        if _declared != choice:
            raise RuntimeError(
                f"the UI {_declared[0]!r} is declared already; a process serves one UI"
            )
        return

    declare_catalog()
    from newswitch.bloks import jonda  # noqa: F401  (declaration side effect)

    if config.ui == "standard":
        from newswitch.bloks import standard

        standard.declare()
    elif config.ui == "minimal":
        from newswitch.bloks import minimal

        minimal.declare()
    else:
        from newswitch.bloks import design
        from newswitch.design.config import design_config

        assert config.design is not None  # ImswitchConfig refuses ui=design without one
        design.declare(config.design, design_config(config.design), CATALOG_NAME)
    _declared = choice
