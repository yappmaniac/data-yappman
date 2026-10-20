# UK W42 publish: wording to revert on the day (checklist for the first rebased UK publish, about Monday 26 Oct 2026)

Written 19 Oct 2026, revised 20 Oct after the second security review. This repository is PUBLIC, so this file is visible
on GitHub even though docs/ is excluded from the Pages build; it holds no dates or numbers that are not already public
on the site, except the planned "about 26 Oct" above, which is a plan, not a promise.

## Push-time step for the wording branch (fix/uk-publish-state-v3, before the W42 revert)

The sitemap lastmod is not in that diff. On the push day build the page list mechanically and set only those pages, in bash (PowerShell can drop an empty argument):

    git diff --name-only main..HEAD -- '*.html'     (x/index.html -> x/ ; the root index.html -> home)
    node docs/release/set-lastmod.js YYYY-MM-DD page/ page/ ...      (use the word home for the home page: Git Bash turns a bare / into a Windows path)

The script checks the date (real, within one day of today), escapes the paths, and writes nothing unless every named page exists in the sitemap. It does NOT check that the list is complete or that the pages are really changed, so afterwards run `git diff sitemap.xml`: it must show only lastmod lines, for exactly the pages in the list (a home-page hunk only if the guide-links commit ships), and `git diff --stat sitemap.xml` must show no line-ending noise. A lastmod on an unchanged page is wrong. Commit it in the same push.

## Trigger

Run the revert only when the public dataset `uk-shelf-price-index` HOLDS W42 and W43 and the files are verified (the vintage is
in the dataset; the UK session's publish check has passed). The trigger is the data, not the date. Until then the
site says the latest published UK week is 2026-W40 and that the index "will restart" at W42.

## How

Prepared in this repo as `docs/release/uk-w42-revert.js`. On a branch off the then-current main, in the SAME push as the
check that the dataset holds W42:

    node docs/release/uk-w42-revert.js YYYY-MM-DD      (the publish date)

It is atomic: it checks every phrase in every file in memory first and writes nothing if any is missing ("NOTHING WRITTEN"); otherwise it applies all the edits below and sets the sitemap lastmod of the pages it touches to the publish date. The date must be a real date within one day of today. The script reads files as LF and writes LF (the repo's autocrlf setting restores the working-tree line endings; no other change). Then run the static check and the JSON-LD check, and the acceptance test.

## What it changes

- shelf-price-index/index.html: meta and og description ("Latest week 2026-W40; restart at W42 pending." → "Base 100 at 2026-W42 after the skipped week 41."), the JSON-LD bracket "(not yet published; the latest published week is 2026-W40)", the sub-heading ("will restart" → "restarted"; "which has not been published yet. The latest published week is 2026-W40." removed), the method box "(not published yet)".
- shelf-price-index/method/index.html: base paragraph ("will restart ... which has not been published yet (the latest published week is 2026-W40)" → "restarted"), the 12 Oct changelog line ("restarted"), and a new changelog entry with the publish date ("2026-W42 published as the new base (level 100)"; no W43 claim).
- methodology/index.html: Base row "(not published yet)" removed.
- press/index.html: "will restart ... once it is published" → "restarted".
- notices/index.html (pill and heading) and notices/w41-skipped/ (title, description, og:title, og:description, h1, body → "restarted"; "Published on <date>." added after "Posted 12 October 2026.").
- sitemap.xml: lastmod = publish date for /shelf-price-index/, /shelf-price-index/method/, /methodology/, /press/, /notices/, /notices/w41-skipped/.

## Not changed by the script (do by hand if needed)

- The UK data dictionary and the AU pages (the "restarted at W42" wording is UK only). Pages touched by hand also need their sitemap date set: /shelf-price-index/data-dictionary/, /au-shelf-price-index/ pages, the home page if the guide-links commit ships, and the guide if touched.
- The page script of shelf-price-index/index.html: the legend "New series (from week 42 ...): not published yet" and the archive row "No weeks published yet. The series will restart with week 42 ..." appear only while no new-series vintage exists in the dataset. They self-clear; check they are gone in the browser. They are code strings, so the acceptance grep below will still list them (lines near 244 and 322): that is expected.
- The live guide (guides/uk-supermarket-price-data/index.html) says the index "is intended weekly, normally on Monday, when a complete week is available" and "first published on 5 October 2026": no change needed unless the cadence changes.

## Acceptance test (after the revert)

A case-insensitive search of the non-docs HTML must return no hits for: "not published yet", "not yet published",
"has not been published", "will restart", "will therefore restart", "latest published week", "latest week 2026-W40",
"restart at W42 pending", "restarts at", "restarts with", except the two code strings in the page script named above.

    grep -rniE "not published yet|not yet published|has not been published|will restart|will therefore restart|latest published week|latest week 2026-W40|restart at W42 pending|restarts at|restarts with" --include=*.html --exclude-dir=_held --exclude-dir=docs .

## After the publish

- The UK cite box shows vintage 2026-W42 or later (read at load time from the dataset).
- Anonymous download of the UK and AU CSV and JSON links works. The setting "anyone with the id can read" is as reported by the UK and AU sessions; it has not been tested without an account, and the site wording ("readable by anyone with the id") describes the setting.
- The next AU vintage: the dated AU W42 sentences stay accurate; add a dated note for that vintage only if the promotion-swing warning fires, rather than editing them.
