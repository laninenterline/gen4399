# gen4399 C 版构建
CC      ?= cc
CFLAGS  ?= -O2 -std=c11 -D_GNU_SOURCE -Wall -Wextra -Iinclude
LDLIBS  ?= -lcurl -lcrypto

SRC = src/crypto.c src/rules.c src/http.c src/submit.c src/main.c
BIN = build/gen4399

# 自带加密实现（不依赖 OpenSSL），用于交叉编译到 Android
SELF_SRC = src/crypto_self.c src/rules.c src/payload.c
AGENT_SRC = src/crypto_self.c src/rules.c src/payload.c src/agent.c src/agent_selftest.c
SELF_BIN = build/gen4399-self
AGENT_BIN = build/gen4399-agent

all: $(BIN)

$(BIN): $(SRC) include/gen4399.h
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $(SRC) $(LDLIBS)

# 自实现加密版：验证与 OpenSSL 版逐字节一致
$(SELF_BIN): $(SELF_SRC) src/selftest.c include/gen4399.h include/payload.h
	@mkdir -p build
	$(CC) $(CFLAGS) -DGEN4399_SELF_CRYPTO -o $@ $(SELF_SRC) src/selftest.c

$(AGENT_BIN): $(AGENT_SRC) src/agent.h include/gen4399.h include/payload.h
	@mkdir -p build
	$(CC) $(CFLAGS) -DGEN4399_SELF_CRYPTO -o $@ $(AGENT_SRC)

test: $(BIN) $(SELF_BIN) $(AGENT_BIN)
	./$(BIN) selftest
	./$(SELF_BIN)
	./$(AGENT_BIN)

clean:
	rm -rf build

.PHONY: all test clean
