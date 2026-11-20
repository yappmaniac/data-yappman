# Data dictionary: 360giving-a-team-foundation-sample-95-grants.csv

95 grants, GBP 4,015,291 in total (smallest 820, largest 735,267), award dates 2019-05-24 to 2024-12-13. Programmes: Main 57, Family 16, Urgent 11, 1%FTP 6, Farming the Future 5. Read 19 November 2026.

| Column | Meaning |
|---|---|
| Identifier | Grant identifier as published (360G-AteamFdn-...) |
| Title | Grant title as published |
| Currency | GBP for all rows |
| Amount Awarded | Amount in the currency |
| Award Date | YYYY-MM-DD |
| Recipient Org:Identifier | Recipient organisation identifier as published (GB-CHC-..., GB-COH-..., US-EIN-... and so on). A few contain stray spaces or punctuation, left as published |
| Recipient Org:Name | Recipient name as published |
| Funding Org:Identifier | Funder identifier as published |
| Funding Org:Name | Funder name as published |
| Grant Programme:Title | Programme name |
| recipient_id_scheme | Added by Yappman Data: the identifier prefix (GB-CHC 46, GB-COH 16, GB-MPR 3, other schemes 25); blank for the five Farming the Future rows (identifier 360G-FTF) |
| licence | Added: CC BY 4.0 |
| attribution | Added: attribution text for each row |

Removed from the source file: Grant Ref, Description, Recipient Org, Funding Org, FY.
