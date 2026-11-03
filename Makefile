PYTHON ?= .venv/bin/python
NETWORK ?= mainnet
DEPLOY_NETWORK ?= testnet

.PHONY: setup demo prices verify-discovery test-discovery paper-demo contracts-setup contracts-test contracts-fork-test prepare-deployment record-deployment verify-decision keeper telegram verify-paper-flow verify-signed-fork

setup:
	UV_CACHE_DIR="$(CURDIR)/.cache/uv" UV_PYTHON_INSTALL_DIR="$(CURDIR)/.python" uv sync --frozen --python 3.12
	npm ci --ignore-scripts

demo:
	npm run dev

.PHONY: demo-testnet
demo-testnet:
	npm run dev -- --testnet --i-understand-testnet $(ARGS)

.PHONY: db-init db-status db-backup
db-init:
	$(PYTHON) -m scripts.local_database init

db-status:
	$(PYTHON) -m scripts.local_database status

db-backup:
	$(PYTHON) -m scripts.local_database backup $(ARGS)

prices:
	PYTHONPATH=agent $(PYTHON) -m aegis.prices --network $(NETWORK) $(ARGS)

verify-discovery:
	PYTHONPATH=agent $(PYTHON) -m aegis.discovery $(ARGS)

test-discovery:
	PYTHONPATH=agent $(PYTHON) -m pytest agent/tests -q

paper-demo:
	PYTHONPATH=agent $(PYTHON) -m aegis.paper_demo $(ARGS)

contracts-setup:
	$(PYTHON) -m scripts.setup_contract_tools

contracts-test:
	cd contracts && ../.tools/foundry/forge test -vv

contracts-fork-test:
	cd contracts && AEGIS_LIVE_ORACLE_TESTS=true ../.tools/foundry/forge test --fork-url https://testnet.hsk.xyz --no-storage-caching --match-contract LiveForkTest -vv

prepare-deployment:
	PYTHONPATH=agent $(PYTHON) -m aegis.deploy prepare --network $(DEPLOY_NETWORK) $(ARGS)

record-deployment:
	PYTHONPATH=agent $(PYTHON) -m aegis.deploy record --network $(DEPLOY_NETWORK) $(ARGS)

verify-decision:
	PYTHONPATH=agent $(PYTHON) -m aegis.verify_decision $(ARGS)

keeper:
	$(PYTHON) -m aegis.keeper $(ARGS)

telegram:
	$(PYTHON) -m aegis.nl.telegram_bot

verify-paper-flow:
	$(PYTHON) -m scripts.verify_aegis_flow --i-understand-paper $(ARGS)

verify-signed-fork:
	$(PYTHON) -m scripts.verify_aegis_fork_flow

.PHONY: deploy-hsk-testnet deploy-hsk-mainnet prove-hsk-testnet prove-hsk-mainnet hsk-deployment-status
deploy-hsk-testnet:
	$(PYTHON) -m scripts.deploy_and_verify_hsk deploy --network testnet $(ARGS)

deploy-hsk-mainnet:
	$(PYTHON) -m scripts.deploy_and_verify_hsk deploy --network mainnet $(ARGS)

prove-hsk-testnet:
	$(PYTHON) -m scripts.deploy_and_verify_hsk prove --network testnet $(ARGS)

prove-hsk-mainnet:
	$(PYTHON) -m scripts.deploy_and_verify_hsk prove --network mainnet $(ARGS)

hsk-deployment-status:
	$(PYTHON) -m scripts.deploy_and_verify_hsk status --network $(DEPLOY_NETWORK) $(ARGS)
