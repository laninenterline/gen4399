# gen4399 C 版构建
CC      ?= cc
CFLAGS  ?= -O2 -std=c11 -Wall -Wextra -Iinclude
LDLIBS  ?= -lcurl -lcrypto

SRC = src/crypto.c src/rules.c src/http.c src/submit.c src/main.c
BIN = build/gen4399

all: $(BIN)

$(BIN): $(SRC) include/gen4399.h
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $(SRC) $(LDLIBS)

test: $(BIN)
	./$(BIN) selftest

clean:
	rm -rf build

.PHONY: all test clean
