CC      = gcc
CFLAGS  = -O2 -Wall -g -Isrc
SRC     = src
BUILD   = build
TARGET  = $(BUILD)/andrey_hammer

all: $(BUILD) $(TARGET)

$(BUILD):
	mkdir -p $(BUILD)

$(TARGET): $(SRC)/andrey_hammer.c
	$(CC) $(CFLAGS) -o $@ $< -lm

clean:
	rm -rf $(BUILD)

.PHONY: all clean
