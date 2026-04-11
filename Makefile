.PHONY: help install-backend install-backend-global install-backend-venv install-frontend install-all run-backend run-frontend run-all

ifeq ($(OS),Windows_NT)
BACKEND_VENV_PYTHON := backend/.venv/Scripts/python.exe
else
BACKEND_VENV_PYTHON := backend/.venv/bin/python
endif

help:
	@echo "Available targets:"
	@echo "  make install-backend        Install backend libs globally and in backend/.venv"
	@echo "  make install-backend-global Install backend libs globally"
	@echo "  make install-backend-venv   Create backend/.venv and install backend libs"
	@echo "  make install-frontend       Install frontend libs (frontend/nextjs)"
	@echo "  make install-all            Install backend + frontend libs"
	@echo "  make run-backend            Start FastAPI backend"
	@echo "  make run-frontend           Start Next.js frontend"
	@echo "  make run-all                Start backend + frontend together"

install-backend: install-backend-global install-backend-venv

install-backend-global:
	python -m pip install --upgrade pip
	python -m pip install -r requirements.txt

install-backend-venv:
	python -m venv backend/.venv
	$(BACKEND_VENV_PYTHON) -m pip install --upgrade pip
	$(BACKEND_VENV_PYTHON) -m pip install -r requirements.txt

install-frontend:
	cd frontend/nextjs && npm install

install-all: install-backend install-frontend

ifeq ($(OS),Windows_NT)
run-backend:
	powershell -NoProfile -Command "Set-Location backend; if (Test-Path .venv/Scripts/python.exe) { ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload } else { python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload }"

run-frontend:
	powershell -NoProfile -Command "Set-Location frontend/nextjs; npm run dev"

run-all:
	powershell -NoProfile -Command "Start-Process powershell -ArgumentList '-NoExit','-Command','Set-Location ''backend''; if (Test-Path .venv/Scripts/python.exe) { ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload } else { python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload }'; Start-Process powershell -ArgumentList '-NoExit','-Command','Set-Location ''frontend/nextjs''; npm run dev'; Write-Host 'Backend and frontend launched in separate terminals.'"
else
run-backend:
	cd backend && if [ -x .venv/bin/python ]; then .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload; else python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload; fi

run-frontend:
	cd frontend/nextjs && npm run dev

run-all:
	( cd backend && if [ -x .venv/bin/python ]; then .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload; else python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload; fi ) &
	cd frontend/nextjs && npm run dev
endif
