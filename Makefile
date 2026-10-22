SCENARIO ?= bad_deploy
PSQL = docker compose exec -T postgres psql -U opspilot -d opspilot

.PHONY: up down nuke break heal status scenarios logs psql counts recent-errors test

up:
	docker compose up -d --build

down:
	docker compose down

nuke:  ## stop everything and delete all data
	docker compose down -v

break:  ## make break SCENARIO=bad_deploy
	python scripts/inject_failure.py start $(SCENARIO)

heal:
	python scripts/inject_failure.py reset

status:
	python scripts/inject_failure.py status

scenarios:
	python scripts/inject_failure.py list

logs:
	docker compose logs -f target-app

psql:
	docker compose exec postgres psql -U opspilot -d opspilot

counts:
	$(PSQL) -c "SELECT level, count(*) FROM log_events GROUP BY level ORDER BY 2 DESC;"
	$(PSQL) -c "SELECT metric, count(*), round(avg(value)::numeric,3) AS avg FROM metric_points GROUP BY metric;"

recent-errors:
	$(PSQL) -c "SELECT ts, message FROM log_events WHERE level='ERROR' ORDER BY ts DESC LIMIT 10;"

test:
	pytest -q
