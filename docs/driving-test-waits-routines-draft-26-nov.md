# Driving test waits: proposed routine text (DRAFT, 26 Nov 2026)

For the Orchestrator to adopt into its own docs/routines.md if Russell agrees. Nothing here is a standing instruction until then, and
nothing in the Orchestrator repo was edited from this worktree.

## Monthly check, from the second Wednesday (9 Dec 2026), every month after

1. `python -I -B docs/release/fetch_driving_test_waits.py --status` in the data-site checkout. It makes ONE keyless GET of the gov.uk
   content API (the same single read the plan, section 4.9, describes), saves nothing, and prints one JSON line. The dates it
   reports are the gov.uk PAGE's: the page also changes for the theory-test files and other edits, so a later page date is NOT
   by itself a new data release.
   - `up-to-date`: nothing to do.
   - `newer-release` (the release date derived from the page is later than the published vintage): the data files' own date has
     to be read before anything is announced, and that needs the files. Ask Russell for the typed go to fetch the four public
     files (about 4.5 MB), saying it is to check the files' own dates. After the fetch, `driving_test_waits_site.py --describe`
     prints the DRT122F cover sheet; confirm its "Last updated" date is the new release and that the data now runs to the month
     before it. Only then say a new vintage is ready to build and ask for the go that names it (the build is a separate go).
   - `updated-since` (same release, the gov.uk page changed since the published vintage): a prompt to look, not news. Do not
     treat it as a new data release. Ask for the same fetch go only if there is a reason to think DRT122F or DRT121G was
     re-issued (the 13 Nov 2026 fix to the 11 Nov release is the example); otherwise record "page changed, data files not
     checked" and do nothing.
   - `nothing-published`: the first vintage has not been published yet.
2. `python -I -B docs/release/check_driving_test_freshness.py`: exit 0 means the published release is under 45 days old and the page
   states the same month and release as the files. Exit 3 (`stale`, `page-out-of-step`) is raised to Russell the same day.
3. Standing go question for Russell: is `--status` (one keyless GET, no download) covered by a standing go for the monthly check?
   `--dry-run` and `--fetch` are NOT: each fetch needs a typed go that names the vintage.

## Building a new vintage (only on that typed go)

`fetch_driving_test_waits.py --fetch` (four public files, once each) then
`driving_test_waits_site.py --check`, then `--publish`, then the publish-day checks in `docs/release/index-publish-checklist.md`
(site-template, check-dataset-ld, check-affiliate-disclosure, check-site-size, check_driving_test_freshness), then push on a typed go
naming the commit. A header change or an unknown code stops the build (exit 3) and writes nothing: tell Russell, do not adjust the
parser without a review.

## Long-chain go for monthly vintages (decision D3, recommended in the plan, NOT yet given)

Proposed wording for Russell to type, if he wants it: "One go covers each monthly DVSA driving-test vintage after the first: fetch the
four public files, build, run the checks, and push the page and data files, as long as every check is clean and the build reports no
header or code change." Until he gives it, each vintage needs its own go, and the page says only that DVSA releases the figures
monthly and that the page is refreshed after each release.

## The 24th monthly check: size runway (review finding 13)

Each vintage adds about 12.6 MB to the served tree (archive CSV and JSON for the three tables; the latest files are rewritten in
place). Run `node docs/release/check-site-size.js` in the data-site checkout, then vintages left to the 600 MB warn line =
(600 - served MB) / 12.6, and write the month the line is reached. At 249 MB that is about 28 vintages. Git history grows by about
25 MB uncompressed a month as well.

## Footer licence sentence (review finding 7): DRAFT, not applied

The site footer and robots.txt say "The free index and basket datasets listed on this site are released under CC BY 4.0." The new
page's URL contains "index" and its data is under the Open Government Licence v3.0, so the sentence could be read as covering it.
Proposed replacement, as a separate template change under its own go: "The free Shelf-Price indices and basket datasets listed on
this site are released under CC BY 4.0; tables built from public sector data state their own licence on their page."
(`_template/footer.tpl`, then `node docs/release/site-template.js --write`, which touches every page; robots.txt is edited by hand.)
