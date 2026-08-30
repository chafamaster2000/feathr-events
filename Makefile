.PHONY: up down logs health rebuild clean lint

up:            ## Levanta todo el stack
	docker compose up -d --build

down:          ## Baja los contenedores (conserva los volumenes)
	docker compose down

logs:          ## Sigue los logs de la API
	docker compose logs -f api

health:        ## Estado de las tres dependencias
	@curl -s http://localhost:8000/health | python3 -m json.tool

rebuild:       ## Rebuild sin cache
	docker compose build --no-cache api

clean:         ## Baja todo y BORRA los volumenes (se pierden los datos)
	docker compose down -v

lint:
	uv run ruff check app && uv run ruff format --check app
