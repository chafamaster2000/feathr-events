.PHONY: up down logs health rebuild clean lint seed reindex logcheck

up:            ## Start the whole stack
	@mkdir -p .logs/agent && chmod -R 777 .logs
	docker compose up -d --build

down:          ## Stop containers, keep volumes
	docker compose down

logs:          ## Follow the API logs
	docker compose logs -f api

health:        ## Formatted /health
	@curl -s http://localhost:8000/health | python3 -m json.tool

rebuild:       ## Rebuild without cache
	docker compose build --no-cache api

clean:         ## Stop everything and DELETE volumes (data is lost)
	docker compose down -v

seed:          ## Fill the stores with realistic events, through the API
	uv run python scripts/seed.py $(ARGS)

reindex:       ## Rebuild the Elasticsearch index from MongoDB
	uv run python scripts/reindex.py $(ARGS)

logcheck:      ## Warnings and errors from the four backend containers, in one stream
	uv run python scripts/logcheck.py $(ARGS)

lint:
	uv run ruff check app && uv run ruff format --check app
