#!/bin/bash
# Every 2h: push museum content (db snapshot + new images) to bae_llm (museum.grining.eu)
set -e
sqlite3 ~/museum/data/museum.db ".backup /tmp/museum-snap.db"

# Non-free wing (paintings.nonfree=1): images sourced outside Commons, still
# under copyright. Tailnet-only — scrub the rows from the public snapshot and
# keep their image files (and thumbs) out of the rsync.
sqlite3 /tmp/museum-snap.db <<'SQL'
PRAGMA foreign_keys=OFF;
DELETE FROM room_paintings WHERE qid IN (SELECT qid FROM paintings WHERE nonfree=1);
DELETE FROM painting_fts   WHERE qid IN (SELECT qid FROM paintings WHERE nonfree=1);
DELETE FROM paintings WHERE nonfree=1;
SQL

sqlite3 -noheader -list ~/museum/data/museum.db \
  "SELECT image_file FROM paintings WHERE nonfree=1 AND image_file NOT LIKE 'http%'" \
  > /tmp/museum-nonfree-imgs.txt
sed 's/\.jpg$/.webp/; s|^|thumbs/|' /tmp/museum-nonfree-imgs.txt > /tmp/museum-nonfree-thumbs.txt
cat /tmp/museum-nonfree-imgs.txt /tmp/museum-nonfree-thumbs.txt > /tmp/museum-nonfree-excl.txt

rsync -a /tmp/museum-snap.db bae_llm:/opt/museum/data/museum.db
rsync -a --exclude-from=/tmp/museum-nonfree-excl.txt ~/museum/data/images/ bae_llm:/opt/museum/data/images/
ssh bae_llm "chown -R www-data:www-data /opt/museum/data && systemctl restart museum.service"
