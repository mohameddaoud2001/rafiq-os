install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -q

run:
	uv run python -m rafiq.cli serve --host 0.0.0.0 --port 8000 --reload

serve:
	uv run python -m rafiq.cli serve --host 0.0.0.0 --port 8000

demo:
	uv run python -m rafiq.cli demo

up:
	docker compose up -d --wait

down:
	docker compose down -v

verify:
	bash scripts/verify.sh
