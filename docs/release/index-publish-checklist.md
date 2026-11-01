# Index publish-day checklist (UK and AU shelf-price index pages)

Done by the Data Website session in the same push as the weekly figures, after the weekly vintage is in the public dataset.

- [ ] `dateModified` in the Dataset JSON-LD on `/shelf-price-index/` and `/au-shelf-price-index/` is set to the publish date (yyyy-mm-dd). Check it parses: `node` over the page's `application/ld+json` blocks, or the site's structured-data check.
- [ ] `docs/release/stamp-latest.js` run and `--check` clean.
- [ ] `docs/release/set-lastmod.js` run for the pages that changed (sitemap `lastmod`).
- [ ] Wording lint: 0 errors.
- [ ] After the push: IndexNow run succeeded; the live pages carry the new dates.
