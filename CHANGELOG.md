# Changelog for plugin *topobank-rest-api*

<!--
Style for this changelog (keep to it so entries stay uniform):

- Newest version first. Heading `vX.Y.Z (DDMonYY)`, underlined with dashes.
  A version not yet released is headed `vX.Y.Z (not yet released)`.
- One bullet per user-visible change, at most two lines (about 200
  characters). Say what changed for the user and, if useful, why or by how
  much. Omit internals: no function, class, file or variable names, no
  environment variables, no commit or PR references.
- Start every bullet with one of: `ENH:` (new feature), `BUG:` (fix),
  `API:` (interface change), `PERF:` (speed or memory), `MAINT:`, `TST:`,
  `DOC:`, `BUILD:`, `CI:`.
- Small related fixes may share one bullet. No trailing period on bullets.
-->

v1.4.0 (04Aug26)
----------------

- ENH: The v2 analysis-result list can be filtered by a set of ids, so a client
  polls the task states of a whole batch of analyses in a single request
- ENH: The v2 analysis-result list reports memory use, duration and submission,
  start and end times, saving a detail request per finished result
- ENH: The v2 analysis-result list computes permissions once per distinct
  permission set per request instead of once per result

v1.3.0 (04Aug26)
----------------

- ENH: Listing the measurements of a dataset through the v1 API costs a
  handful of database queries instead of about ten per measurement

v1.2.0 (04Aug26)
----------------

- ENH: The v2 dataset list embeds a short summary of each measurement (name,
  task state, thumbnail), so a dataset list renders from a single response
- ENH: The v2 dataset list supports the filters of v1: full-text search,
  sharing status, author (combined with AND), latest version only, name order
- ENH: The v2 dataset list computes permissions once per distinct permission
  set per request, as the measurement list already did
- ENH: The v2 dataset API reports whether a dataset is own, shared or published
- API: Listing measurements through v2 no longer starts an inspection task for
  each uninspected row; inspection now starts only when one is fetched alone
- BUG: A dataset created through v2 without a name is named "Digital surface
  twin" with its id, as in v1

v1.1.0 (03Aug26)
----------------

- API: Removed two unused, unauthorized endpoints that let any user rename or
  re-share an analysis result; use normal updates and the authorization API
- API: The analysis memory-usage report is restricted to staff; it covered
  every analysis in the instance and was readable without logging in
- ENH: Measurements report the fraction of undefined data and the trend that
  detrending subtracted
- ENH: The dataset list shows only the latest published version of a dataset,
  so a search no longer returns the same dataset once per version
- ENH: Analysis plots are labelled in a unit that suits the data, so an axis
  no longer reads 1.000e-4 mm; both axes share one base length unit
- PERF: Analysis cards read only the metadata of the first analysis instead of
  fetching every data series of its result
- BUG: The task dashboard falls back to the username when a user's name is
  blank

v1.0.0 (31Jul26)
----------------

- MAINT: Initial release, containing the REST API implementation that was
  previously part of topobank and ce-ui
- ENH: Search endpoints
- ENH: Endpoints for the user and task dashboards
- ENH: Asynchronous ZIP download
- ENH: Workflow descriptions are exposed through the API
- BUG: Forcing a re-inspection also restarts inspections already in progress
- BUG: The API exposes how a workflow is visualized, so analysis cards render
- BUG: The user API reports whether a user is staff
- BUG: The API schema lists the allowed values of permission levels and
  describes the entry-points endpoint correctly
- MAINT: All remaining REST functionality (serializers, filters, pagination,
  permissions, upload instructions) moved here from topobank
- MAINT: Removed organization management and organization-based sharing
- MAINT: Removed django-guardian and per-workflow permission checks
- MAINT: Analysis functions are called workflows and folders manifest sets; the
  separate per-subject dispatch was removed
- BUILD: The package builds with hatchling and depends on
  django-termsandconditions
