"use strict";
// One source for the Apify affiliate parameter, the rel value and the disclosure line, used by the page builders and by
// docs/release/check-affiliate-disclosure.js. Rules (set by Russell and Apify's affiliate terms, 12 Nov 2026):
//  - only links to our own Actors (https://apify.com/yappman/...) carry the parameter; never the menu, never plain-text or
//    machine-readable files (llms.txt, data/*.txt), never structured data;
//  - an existing query (utm tags) is kept as it is; the parameter is added after it;
//  - every link that carries it has rel="sponsored", and its page carries the disclosure line.
const TOKEN = "wy5pu7";
const PARAM = "fpr=" + TOKEN;
const REL = "sponsored";
const DISCLOSURE_ID = "affiliate-disclosure";
const DISCLOSURE_TEXT = "Some links to Apify are affiliate links: if you sign up through them we may earn a commission.";
const DISCLOSURE_HTML = `<p class="meta" id="${DISCLOSURE_ID}">${DISCLOSURE_TEXT}</p>`;
const OWN_ACTOR = /^https:\/\/apify\.com\/yappman\/[a-z0-9-]+/;
const hasParam = href => /[?&](?:amp;)?fpr=/.test(href);
// href as written inside an HTML attribute ("&amp;" between query parameters)
const withParam = href => (hasParam(href) ? href : href + (href.includes("?") ? "&amp;" : "?") + PARAM);

module.exports = { TOKEN, PARAM, REL, DISCLOSURE_ID, DISCLOSURE_TEXT, DISCLOSURE_HTML, OWN_ACTOR, hasParam, withParam };
