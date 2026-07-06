#!/bin/bash
set -e
echo "=== Собираем hammer ==="
gcc -O0 -o /tmp/hammer /mnt/c/Users/Dan/damo/hammer/hammer.c
HZ=${1:-2000}
DURATION=${2:-10}
PAGES=${3:-10}
OUTFILE=/tmp/hammer_$$.txt   # уникальный файл на каждый запуск

# убиваем старые hammer если висят
pkill -f /tmp/hammer 2>/dev/null || true
# останавливаем зависший kdamond если есть
STATE_FILE=/sys/kernel/mm/damon/admin/kdamonds/0/state
[ -e "$STATE_FILE" ] && echo off > "$STATE_FILE" 2>/dev/null || true
sleep 0.3

echo "=== Запускаем hammer на ${HZ} Hz ==="
/tmp/hammer $HZ $PAGES > $OUTFILE 2>&1 &
HAMMER_PID=$!
echo "hammer PID=$HAMMER_PID"

sleep 1.5
cat $OUTFILE

# берём hex-адреса из вывода hammer (-a = форсировать текстовый режим)
REGION_LINE=$(grep -a "^REGION:" $OUTFILE | head -1)
HEX_START=$(echo $REGION_LINE | awk '{print $2}' | cut -d- -f1)
HEX_END=$(echo   $REGION_LINE | awk '{print $2}' | cut -d- -f2)

if [ -z "$HEX_START" ] || [ -z "$HEX_END" ]; then
    echo "ERROR: не смогли прочитать адрес региона из вывода hammer"
    echo "Содержимое файла:"
    cat $OUTFILE
    kill $HAMMER_PID 2>/dev/null || true
    exit 1
fi

DEC_START=$(python3 -c "print(int('$HEX_START', 16))")
DEC_END=$(python3   -c "print(int('$HEX_END',   16))")
SIZE_KB=$(python3   -c "print(($DEC_END - $DEC_START) // 1024)")

echo ""
echo "Регион: ${HEX_START}-${HEX_END} = ${DEC_START}-${DEC_END} (${SIZE_KB} KB)"

echo ""
echo "=== Генерируем конфиг DAMON ==="
KDAMONDS=$(damo args damon \
    --ops fvaddr \
    --target_pid $HAMMER_PID \
    -r "${DEC_START}-${DEC_END}" \
    --monitoring_intervals 5ms 100ms 1s \
    --format json)

echo "$KDAMONDS" | python3 -m json.tool 2>/dev/null | head -50

echo ""
echo "=== Запускаем damo record на ${DURATION}с ==="
rm -f /root/damon_test.data
damo record \
    --kdamonds "$KDAMONDS" \
    --timeout $DURATION \
    -o /root/damon_test.data

echo ""
echo "=== РЕГИОНЫ (первые 5 снапшотов) ==="
python3 - /root/damon_test.data << 'PYEOF'
import sys
sys.path.insert(0, '/usr/local/lib/python3.12/dist-packages/damo')
import _damo_records
records, err = _damo_records.get_records(record_file=sys.argv[1])
for record in records:
    aggr_us = record.intervals.aggr if record.intervals else None
    for i, snap in enumerate(record.snapshots):
        nr = len(snap.regions)
        acc = [r.nr_accesses.samples for r in snap.regions]
        hz  = [round(r.nr_accesses.in_hz(aggr_us), 1) for r in snap.regions] if aggr_us else acc
        print(f"  snap {i:3d}: {nr} regions  samples={acc}  hz={hz}")
       
PYEOF

echo ""
echo "=== ХИТМАП ==="
damo report heatmap --input /root/damon_test.data --resol 2 1

echo ""
echo "Ожидаемый макс: 200 Hz  (1/sample_interval = 1/5ms)"

kill $HAMMER_PID 2>/dev/null || true
wait $HAMMER_PID 2>/dev/null || true
rm -f $OUTFILE
