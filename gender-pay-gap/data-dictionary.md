# Data dictionary: gender-pay-gap-2025-26-sample-2000-rows.csv

Source: https://gender-pay-gap.service.gov.uk/viewing/download-data/2025 | Retrieved: 19 Nov 2026 | Rows: 2,000 | Selection: random sample, seed 19, of the 11,202 source rows that have a CompanyNumber. A sample of the public file.

| Column | Meaning |
|---|---|
| EmployerName | Employer name as listed in the source |
| EmployerId | Gender pay gap service employer id |
| PostCode | Employer postcode |
| CompanyNumber | Companies House number (text, leading zeros kept) |
| SicCodes | SIC codes as given in the source (may hold several, separated by a comma and line break) |
| DiffMeanHourlyPercent | Mean hourly pay gap, percent |
| DiffMedianHourlyPercent | Median hourly pay gap, percent |
| DiffMeanBonusPercent | Mean bonus pay gap, percent |
| DiffMedianBonusPercent | Median bonus pay gap, percent |
| EmployerSize | Size band, as text |
| CurrentName | Current employer name in the source |
| SubmittedAfterTheDeadline | True/False |
| DueDate | Reporting deadline (yyyy/mm/dd hh:mm:ss) |
| DateSubmitted | Submission timestamp (yyyy/mm/dd hh:mm:ss) |
| source | Source URL |
| licence | Open Government Licence v3.0 |
| attribution | Attribution text |
