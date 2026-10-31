up:
	docker compose up --build

seed:
	python scripts/seed.py

reset:
	python scripts/reset.py

test:
	python -m pytest

test-ui:
	playwright install chromium
	python -m pytest tests/ui -v
