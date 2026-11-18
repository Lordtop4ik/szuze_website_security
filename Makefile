UV ?= uv
.PHONY: run pack test docker-build docker-run
run:
	$(UV) run --locked python main.py
pack:
	$(UV) run --locked python main.py --pack
test:
	node tests/shop.test.cjs
	$(UV) run --locked pytest -q
docker-build:
	docker build -t shop-python .
docker-run:
	docker run --rm -p 127.0.0.1:8000:8000 shop-python
