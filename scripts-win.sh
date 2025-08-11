@echo off
REM Docker management scripts for Clearify Backend - Windows Version

if "%1"=="build" (
    echo 🔨 Building Docker containers...
    docker-compose build
    goto end
)

if "%1"=="up" (
    echo 🚀 Starting services...
    docker-compose up -d
    echo ✅ Services started!
    echo API: http://localhost:8000
    echo Docs: http://localhost:8000/docs
    goto end
)

if "%1"=="dev" (
    echo 🔧 Starting development mode...
    docker-compose up
    goto end
)

if "%1"=="down" (
    echo 🛑 Stopping services...
    docker-compose down
    goto end
)

if "%1"=="logs" (
    if not "%2"=="" (
        docker-compose logs -f %2
    ) else (
        docker-compose logs -f
    )
    goto end
)

if "%1"=="shell" (
    echo 🐚 Opening shell in app container...
    docker-compose exec app bash
    goto end
)

if "%1"=="reset" (
    echo 🗑️ Resetting all containers and volumes...
    docker-compose down -v --remove-orphans
    docker-compose build --no-cache
    docker-compose up -d
    goto end
)

if "%1"=="test" (
    echo 🧪 Running tests...
    docker-compose exec app python -m pytest
    goto end
)

echo Usage: %0 {build^|up^|dev^|down^|logs^|shell^|reset^|test}
echo.
echo Commands:
echo   build  - Build Docker containers
echo   up     - Start services in detached mode
echo   dev    - Start services in development mode (with logs)
echo   down   - Stop all services
echo   logs   - Show logs (optionally for specific service)
echo   shell  - Open shell in app container
echo   reset  - Reset everything (containers, volumes, rebuild)
echo   test   - Run tests

:end