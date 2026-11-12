#!/usr/bin/env bash
# check_nextpnr_timing.sh — fail unless every clock met its target frequency.
#
# Usage: check_nextpnr_timing.sh <nextpnr.log> [target_mhz]
#
# nextpnr prints "Max frequency for clock '<name>': <f> MHz (PASS|FAIL at <t> MHz)"
# after placement and again after routing. This reads the LAST such line per
# clock (the routed result), prints a one-line summary per clock, and exits
# non-zero if any clock failed or none were reported. target_mhz is only used
# in the message when the log carries no target of its own.

set -uo pipefail

log="${1:?usage: $0 <nextpnr.log> [target_mhz]}"
target="${2:-}"

if [[ ! -f "$log" ]]; then
    echo "ERROR: nextpnr log not found: $log" >&2
    exit 2
fi

# Last 'Max frequency' line per clock name.
lines=$(grep -E "Max frequency for clock" "$log" \
    | awk -F"'" '{ last[$2] = $0 } END { for (c in last) print last[c] }' | sort)

if [[ -z "$lines" ]]; then
    echo "ERROR: no 'Max frequency' lines in $log -- was the clock constrained?" >&2
    exit 2
fi

status=0
while IFS= read -r line; do
    clock=$(sed -E "s/.*clock '([^']*)'.*/\1/" <<<"$line")
    fmax=$(sed -E 's/.*: ([0-9.]+) MHz.*/\1/' <<<"$line")
    verdict=$(sed -E 's/.*\((PASS|FAIL) at ([0-9.]+) MHz\).*/\1 at \2/' <<<"$line")
    printf '  %-28s %9s MHz   %s\n' "$clock" "$fmax" "$verdict"
    if grep -q "FAIL" <<<"$line"; then status=1; fi
done <<<"$lines"

if [[ $status -ne 0 ]]; then
    echo "TIMING NOT MET${target:+ (target ${target} MHz)}" >&2
else
    echo "Timing met."
fi
exit $status
