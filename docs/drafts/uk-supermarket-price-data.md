<!--
DRAFT, not published. docs/ is excluded from the Pages build (_config.yml), so this file is never served.
Target: data.yappman.com page (path to decide, e.g. /guides/uk-supermarket-price-data/), then a dev.to
cross-post with the canonical URL set to the site page.

Sources: every third-party statement below was read on the publisher's own page on 19 Oct 2026 (research
by the Data Website session; URLs in the "Sources" list at the end). Re-check each before publishing,
because these pages change. Statements marked [CHECK] need a second look before publication.
Our own facts come from data.yappman.com (index pages, method pages, home page pricing) and the
UK Supermarket Price Scraper changelog. No claim about any competitor beyond what its page says.
-->

# Where to get UK supermarket price data: free and paid, compared

If you need UK grocery prices for research, a story or a product, the options split into three kinds:
official statistics, research datasets, and commercial or self-collected data. They differ in what
they measure (price change or price levels, shelf prices or prices paid), how fresh they are, and
whether you can download them and reuse them. This page lists the main ones and what each publisher
says about its own data.

## Official statistics: ONS

The Office for National Statistics publishes the consumer prices index, including the annual rate for
food and non-alcoholic beverages (series D7G8), as a monthly series you can download as CSV or XLS.
Its Shopping prices comparison tool gives average prices for more than 650 items from the CPI basket,
from January 2020, with a "download all data" option; ONS describes those averages as official
statistics in development, from a sample built to measure price change rather than price levels.
An archive of the tool's earlier food data (January 2018 to January 2025) is also downloadable.
All three are published under the Open Government Licence v3.0.

Best for: the official measure of food inflation, monthly. Not for: individual supermarkets or
individual products.

## Research datasets

**University of Warwick, "Price dynamics in food retailing in Great Britain".** Weekly prices for 370
products, from 1 October 2009 to 31 March 2012, with the supermarkets anonymised. [CHECK: "collected
by hand" is the research note's wording; confirm it on the UK Data Service page before using it.]
The UK Data Service lists it as a safeguarded dataset you download after registering, under the UK
Data Service End User Licence.
[CHECK, unresolved conflict: the Warwick repository page (wrap.warwick.ac.uk/134726) says "Creative
Commons open licence" and also "safeguarded", while the UK Data Service page (reshare.ukdataservice.ac.uk/850626)
says safeguarded under its End User Licence. Do not call it openly licensed. Quote only the UK Data
Service terms, or ask the depositor before publishing. The pages also give both three and four
supermarket chains, and "five" and "seven years" for a 2009 to 2012 span: state neither.]

**LSE (Davies, Hellings and Mcevoy).** A seminar listing at LSE (6 February 2024) describes about 19
million online grocery prices collected daily since July 2023 from retailers covering over 70% of UK
grocery spending. We found no public release of the data or terms of use, so we do not list it as
available.

**Kaggle, "Time Series UK Supermarket Data".** Web-scraped prices, collected daily on the days its
creator ran the scraper [CHECK: confirm this wording, and any "gaps" wording, against the creator's own
note on the Kaggle page; the Kaggle HTML page itself was not readable, only its API record], from Aldi, Asda, Morrisons,
Tesco and Sainsbury's, from 9 January 2024, licensed Apache 2.0. Its metadata shows the last update
on 13 April 2024, and its creator notes the scraper is not perfectly reliable, that Morrisons counts
were unstable until 27 January 2024, and that loyalty prices and multibuys are not included.

## Trackers you can read but not download

**Which? supermarket food and drink inflation tracker.** Annual inflation for eight supermarkets
(Aldi, Asda, Lidl, Morrisons, Ocado, Sainsbury's, Tesco and Waitrose) across 20 categories. Which? says
it covers 23,000 to 28,000 products a month [CHECK], weighted by market share and category sales
[CHECK], including discounts but not multibuys or loyalty-card offers. Which? says it moved to once
every three months from December 2023 [CHECK: the current schedule is not stated]. We found no data
download on the page [CHECK].

**Trolley.co.uk Grocery Price Index.** Trolley says the index is built from its price database and the
activity of more than 850,000 shoppers, over 47,711 products typically bought at least once a month,
and runs from May 2020 [CHECK all three figures on the page on the day]. We found no download or API
on the page [CHECK]; it points data enquiries to its contact page.

## Our data: Yappman Data

**UK Online Shelf-Price Index (free, CC BY 4.0).** A weekly index of posted online shelf prices at
Tesco, Sainsbury's, Asda and Aldi: the same products matched week on week by the retailer's own
product id, a geometric mean (Jevons) of their price ratios (equal weight to each product within a
retailer-class cell, equal weight to each retailer, no spending weights), by retailer and by 16
product classes, with matched counts on every row. About 73,000 products a week in the weekly snapshots (73,745 in the week 40 snapshot of 4 October 2026). Published every
Monday at 07:00 UK time since 5 October 2026, each week added once and never revised. The whole series
downloads as one CSV or JSON file with no account. It measures asking prices online, not prices paid,
and it is not a CPI. Method: https://data.yappman.com/shelf-price-index/method/ . Fields:
https://data.yappman.com/shelf-price-index/data-dictionary/ .

**AU Online Shelf-Price Index (free, CC BY 4.0).** The same approach for Coles, Woolworths and Aldi
Australia, weekly from 15 October 2026. https://data.yappman.com/au-shelf-price-index/method/

**Product-level data (paid).** The rows behind the index (product, price, unit price, loyalty price,
promotion text, barcode where the retailer shows one) come from our UK Supermarket Price Scraper on
the Apify Store, priced per product, or as an annual licence of the weekly catalogue or the daily
212-item basket. [CHECK the current Store price and the licence prices on the home page before
publishing; do not restate them from memory.]

## Comparison

| Source | Measures | Period | Frequency | Download | Licence |
| --- | --- | --- | --- | --- | --- |
| ONS CPI food (D7G8) | Official price change | Long-running | Monthly | CSV, XLS | OGL v3.0 |
| ONS Shopping prices tool | Average prices, 650+ items | From Jan 2020 | Monthly | Yes | OGL v3.0 |
| Warwick (UK Data Service) | Weekly prices, 370 products, anonymised stores | Oct 2009 to Mar 2012 | Weekly | After registration | UK Data Service End User Licence |
| LSE (Davies et al.) | Online prices, 19m | From Jul 2023 | Daily | Not found | Not found |
| Kaggle time series | Scraped prices, 5 retailers | Jan to Apr 2024 | Daily, on days the scraper ran [CHECK] | Kaggle | Apache 2.0 |
| Which? tracker | Weighted inflation, 8 supermarkets | Ongoing | Every three months since Dec 2023 [CHECK] | None found [CHECK] | Not stated |
| Trolley index | Index from its own database | From May 2020 [CHECK] | Continuous | None found [CHECK] | Not stated |
| Yappman UK Shelf-Price Index | Matched-product shelf-price change, 4 retailers | From Sep 2026 | Weekly | CSV, JSON | CC BY 4.0 |

## Which to use

- The official rate of food inflation: ONS.
- Supermarket by supermarket, week by week, with the data in a file you can reuse and cite: the
  Yappman Data index (and its method page, to check what it does and does not measure).
- Historical research on 2009 to 2012: the Warwick data through the UK Data Service.
- A headline on which supermarket's prices rose most, with weights: Which?'s tracker (read, not
  downloaded).

Yappman Data is not affiliated with, endorsed by or sponsored by any of the organisations or companies
named on this page, including the supermarkets.

## Sources (read 19 Oct 2026)

- ONS D7G8: https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g8/mm23
- ONS Shopping prices comparison tool: https://www.ons.gov.uk/economy/inflationandpriceindices/articles/shoppingpricescomparisontool/latest
- ONS tool archive (before the 2025 update): https://www.ons.gov.uk/economy/inflationandpriceindices/adhocs/2724shoppingpricescomparisontooldatadownloadbeforethe2025update
- UK Data Service (Warwick): https://reshare.ukdataservice.ac.uk/850626
- Warwick repository: https://wrap.warwick.ac.uk/134726
- LSE seminar listing: https://sticerd.lse.ac.uk/_new/events/event/?index=9306
- Kaggle dataset: https://www.kaggle.com/datasets/declanmcalinden/time-series-uk-supermarket-data (metadata read via Kaggle's public API record)
- Which? tracker: https://www.which.co.uk/reviews/supermarkets/article/food-price-inflation-tracker-aU2oV0A46tu3
- Trolley index: https://www.trolley.co.uk/grocery-price-index/
