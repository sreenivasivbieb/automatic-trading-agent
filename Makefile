PYTHON ?= .venv/bin/python
NETWORK ?= mainnet
DEPLOY_NETWORK ?= testnet

.PHONY: setup prices verify-discovery test-discovery paper-demo contracts-setup contracts-test contracts-fork-test prepare-deployment record-deployment verify-decision

setup:
	UV_CACHE_DIR="$(CURDIR)/.cache/uv" UV_PYTHON_INSTALL_DIR="$(CURDIR)/.python" uv sync --frozen --python 3.12

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
