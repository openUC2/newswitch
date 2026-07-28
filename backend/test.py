"""An entry point for running the application with Uvicorn."""

from newswitch.app import create_app, ImswitchConfig
import uvicorn

if __name__ == "__main__":
    cfg = ImswitchConfig()
    cfg.use_virtual_microscope = False
    app = create_app(cfg)

    uvicorn.run(app, host="0.0.0.0", port=8099)
