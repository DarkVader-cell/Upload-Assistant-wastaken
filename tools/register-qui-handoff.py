#!/usr/bin/env python3
"""Idempotently register QUI context-menu actions for manual Grape handoffs."""
import sqlite3
import sys

database = sys.argv[1]
args = "{content_path}"
mappings = '[{"from":"/mnt/nvme11n1/artemisprime","to":"/mnt/nvme11n1/artemisprime"}]'
programs = (
    (
        "Force selected Clementine release to Grape HDD",
        "/config/ua-handoff-clementine-now",
    ),
    (
        "Force selected non-Uploads Clementine release to Grape HDD",
        "/config/ua-racing-handoff-clementine-now",
    ),
)
obsolete_names = (
    "Force selected Clementine release to Cactus HDD",
    "Force selected non-Uploads Clementine release to Cactus HDD",
    "Transfer Clementine upload to Cactus now",
)

connection = sqlite3.connect(database)
try:
    outcomes = []
    for name in obsolete_names:
        if connection.execute("DELETE FROM external_programs WHERE name = ?", (name,)).rowcount:
            outcomes.append(f"removed obsolete: {name}")
    for name, path in programs:
        row = connection.execute("SELECT id FROM external_programs WHERE name = ?", (name,)).fetchone()
        if row:
            connection.execute(
                "UPDATE external_programs SET path = ?, args_template = ?, enabled = 1, use_terminal = 0, path_mappings = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (path, args, mappings, row[0]),
            )
            outcomes.append(f"updated: {name}")
        else:
            connection.execute(
                "INSERT INTO external_programs (name, path, args_template, enabled, use_terminal, path_mappings) VALUES (?, ?, ?, 1, 0, ?)",
                (name, path, args, mappings),
            )
            outcomes.append(f"created: {name}")
    connection.commit()
    print("\n".join(outcomes))
finally:
    connection.close()
