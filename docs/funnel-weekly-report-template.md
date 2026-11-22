# Sample-to-paid funnel: weekly report template (counts only)

Read each Monday for the week before (Monday to Sunday). Counts only: never a name, an address, an email, a free-text field or a screenshot of a visitor. Design note: Orchestrator drafts/sessions/data-website/sample-funnel-tracking-design-20nov.md.

## Where the counts come from
- **Umami** (the site's cookieless analytics), read in the signed-in browser, read-only. No API key and no new credential. Visitors who send Do Not Track, or block the script, are not counted, so every figure is a floor.
  - Page views per page, and referrers (kaggle.com, huggingface.co, youtube.com, other).
  - The custom event `apify-referral-click`: it carries only the page it was on (`path`) and the Actor page it led to (`target`). It fires for links with the affiliate parameter, so it counts clicks on tagged Actor links and nothing else.
- **Off-site, by hand:** Kaggle (views, downloads, votes per dataset), Hugging Face (downloads per dataset), YouTube (views per video).
- **Apify side, optional, read by Russell in his console:** Store visits and runs for the Actors named in the report, and affiliate sign-ups this week. Never joined to a page by a person.

## The links that are counted (tagged: utm_source=data.yappman.com, utm_medium=referral, utm_campaign=<page slug>, fpr, rel="sponsored")
| Page | utm_campaign | Actor link |
|---|---|---|
| /recalls-sample/ | recalls-sample | UK and EU Product Recalls and Safety Alerts Feed |
| /eu-air-sea-traffic-sample/ | eu-air-sea-traffic-sample | EU Air and Sea Traffic: Eurostat Passenger and Freight Data |
| /sold-prices/history/ | sold-prices-history | UK Property Listings (sold-prices mode) |
| /sold-prices/ | sold-prices | UK Property Listings |
| /sold-prices/history/areas/ | sold-prices-areas | UK Property Listings |
| /free-data/ | free-data | the Actor of each row (11 rows link one) |
| /contracts-sample/ | contracts-sample | UK Government Contracts: Contracts Finder, Find a Tender |
| /lei-sample/ | lei-sample | LEI Lookup: GLEIF Legal Entity Identifier Search & Watch |
| /fsa-sample/ | fsa-sample | FSA Approved Food Establishments: England, Wales, NI |
Pages with no Actor link have no Store clicks to count: /gender-pay-gap/ and /360giving-grants-sample/ (their texts name no Actor: none fits), and the profile link `apify.com/yappman` on the sample pages (the affiliate rule covers links to Actor pages only).

## The report (copy this block, fill the counts)
```
Sample-to-paid funnel, week YYYY-Www (Mon dd Mmm to Sun dd Mmm). Counts only. Do Not Track visitors are not counted.

Page                              Views  From Kaggle  From HF  From YouTube  Store clicks  Target Actor (most clicked)
/gender-pay-gap/                    n         n          n          n             -          -
/360giving-grants-sample/           n         n          n          n             -          -
/recalls-sample/                    n         n          n          n             n          uk-eu-recalls-feed
/eu-air-sea-traffic-sample/         n         n          n          n             n          aviation-airport-traffic-eu
/sold-prices/history/               n         n          n          n             n          uk-property-listings
/sold-prices/                       n         n          n          n             n          uk-property-listings

Off-site (by hand): Kaggle views / downloads / votes per dataset; Hugging Face downloads per dataset; YouTube views per video.
Apify side (Russell's console, optional): Store visits and runs for the Actors above; affiliate sign-ups this week.
Read: one line. Zero clicks in one week is no signal. Two weeks of zero on a page with views is the point to raise a question, not to conclude.
```

## Rules
- Report counts, not rates, until a page has more than about 100 views a week.
- A pass signal for a sample (for example downloads and one enquiry or Store click in four weeks) is Russell's to set; it does not live here.
- A new tagged link, or a new page with one, is added to the table above in the same change.
- Nothing here changes a cookie, a consent notice, the privacy page or any script: the existing Umami script and the existing event do all the counting.
