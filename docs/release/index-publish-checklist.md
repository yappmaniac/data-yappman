# Index publish-day checklist (UK and AU shelf-price index pages)

Done by the Data Website session in the same push as the weekly figures, after the weekly vintage is in the public dataset.

- [ ] `dateModified` in the Dataset JSON-LD on `/shelf-price-index/` and `/au-shelf-price-index/` is set to the publish date (yyyy-mm-dd). Check it parses: `node` over the page's `application/ld+json` blocks, or the site's structured-data check.
- [ ] `docs/release/stamp-latest.js` run and `--check` clean.
- [ ] UK: `docs/release/build-index-files.js --uk FILE --confirm-uk <week>` run with the same JSON file as the stamp (its .csv beside it). It adds the week to `data/uk-shelf-price-index.csv` and `.json` and rewrites `data/uk-shelf-price-index-headline.json`.
- [ ] AU: `docs/release/build-index-files.js --au FILE --confirm-au <week>` run with the same JSON file as the stamp (its .csv beside it). It adds the week to `data/au-shelf-price-index.json`.
- [ ] `docs/release/build-index-files.js --check` clean. The index pages, the home page and `/press/` read these files and never call the dataset, so a week that is stamped but not added here would leave the page showing the week before; `--check` fails on that. The data files go in the SAME commit as the stamp.
- [ ] `docs/release/set-lastmod.js` run for the pages that changed (sitemap `lastmod`).
- [ ] Wording lint: 0 errors.
- [ ] After the push: IndexNow run succeeded; the live pages carry the new dates.
