from uvicorn import run
from api.settings import get_settings


def main():
    settings = get_settings()
    run(
        "api.app:app",
        host=settings.SERVER.HOST,
        port=settings.SERVER.PORT,
        workers=settings.SERVER.WORKERS,
        reload=settings.SERVER.RELOAD,
        reload_dirs=["api"],
        reload_excludes=["__pycache__", "*.pyc", "*.pyo", "*.pyd", "*.pyw", "*.pyz"],
        reload_includes=["*.py"],
    )


if __name__ == "__main__":
    main()