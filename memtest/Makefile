CC      = gcc
CFLAGS  = -O2 -Wall -g -pthread -Isrc
SRC     = src
BUILD   = build
SRCS    = $(wildcard $(SRC)/*.c)
OBJS    = $(SRCS:$(SRC)/%.c=$(BUILD)/%.o)
TARGET  = $(BUILD)/memtest

all: $(BUILD) $(TARGET)

$(BUILD):
	mkdir -p $(BUILD)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ -lm

$(BUILD)/%.o: $(SRC)/%.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -rf $(BUILD)

.PHONY: all clean
