#!/bin/sh
# Fetch the four pinned inputs into this directory, then check them.
#
# They are deliberately NOT committed here: a copy in my own repo is a copy I
# could have edited, and the whole point of the commitments is that the bytes
# come from the publisher. diff_v2.py re-hashes them anyway and aborts on a
# mismatch, so a tampered fetch fails loudly rather than quietly.
set -eu
cd "$(dirname "$0")"

curl -sSfL -o corpus-v2.json  https://ainglish.org/fuzz/corpus-v2.json
curl -sSfL -o reti_outputs.json https://ainglish.org/fuzz/outputs-v2.json
curl -sSfL -o reti_certs.json https://ainglish.org/fuzz/certificates-v2.json
curl -sSfL -o mine_outputs.json \
  https://raw.githubusercontent.com/ColonistOne/claim-audit/main/ainglish-threeway/stratum_b_union_outputs_colonistone.json

sha256sum ./*.json
python3 diff_v2.py
python3 control_diff_v2.py
python3 ud_falsifier.py
