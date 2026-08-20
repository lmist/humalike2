# human — repo-local beads (gastownhall/beads vendored at vendor/beads)
#
# Always prefer ./bin/bd over whatever `bd` is on PATH. System copies drift;
# this one is pinned to the vendor/beads subtree tag below.

VENDOR     := vendor/beads
VENDOR_REF := v1.2.2
BIN        := $(CURDIR)/bin
BD         := $(BIN)/bd
PREFIX     ?= hum
export PATH := $(BIN):$(PATH)

.PHONY: all bd bootstrap formulas hooks types doctor ready clean

all: bd

bd:
	@mkdir -p $(BIN)
	$(MAKE) -C $(VENDOR) BUILD_DIR=$(BIN) build
	@$(BD) version

bootstrap:
	@PREFIX=$(PREFIX) VENDOR_REF=$(VENDOR_REF) ./scripts/bootstrap.sh

formulas:
	@./scripts/check-formulas.sh

hooks:
	@$(BD) hooks install
	@./scripts/install-extra-hooks.sh

types:
	@./scripts/set-types.sh

doctor:
	@./scripts/doctor.sh

ready:
	@$(BD) ready

clean:
	rm -f $(BD) $(BD).exe
