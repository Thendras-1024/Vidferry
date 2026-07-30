"""Start the local Feishu-to-Vidferry Agent bridge."""

from __future__ import annotations

import logging
from pathlib import Path

import sau_backend as backend
from app.feishu_robot import env_settings, run_feishu_robot


def main():
    log_path = Path(backend.BASE_DIR) / "logs" / "feishu_robot.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    backend.init_database_tables()
    app_id, app_secret, allowed_open_ids = env_settings()
    run_feishu_robot(
        app_id,
        app_secret,
        allowed_open_ids,
        backend.run_agent_chat,
        image_roots=(backend.BASE_DIR,),
        sanitize=backend.sanitize_agent_output,
    )


if __name__ == "__main__":
    main()
