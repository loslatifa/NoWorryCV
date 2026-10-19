"""Export API types without initializing stores, credentials, or task workers."""
import json
from pathlib import Path
from fastapi import FastAPI
from backend.app.api.v1.routes import router
from backend.app.api.v1 import profiles, history, applications, quality, interviews, materials, positions, templates


def main():
    app = FastAPI()
    for item in [router, profiles.router, history.router, applications.router, quality.router,
                 interviews.router, materials.router, positions.router, templates.router]:
        app.include_router(item, prefix='/api/v1')
    destination = Path('.dist/openapi.json')
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(app.openapi(), ensure_ascii=False))
    print(destination)


if __name__ == '__main__':
    main()
