# Changelog for plugin *topobank-rest-api*

## 1.1.0 (2026-08-03)

- API: Removed the `set-name` and `set-result-permissions` endpoints. Neither was
  reachable from any client, and neither was authorized: `set-name` let any logged-in
  user rename an arbitrary result and detach it from its subject, and
  `set-result-permissions` granted and revoked access to a result while checking only
  for `view` permission, so a read-only recipient could re-share it. A result is named
  by a normal field update and its permissions are set through the authorization API
- API: `GET /analysis/api/memory-usage/` is restricted to staff. It reports on every
  analysis in the instance, including analyses of datasets the caller cannot see, and
  was readable without authentication
- ENH: Measurement serializers report `undefined_data_fraction`
- ENH: Measurement serializers report `detrend_parameters`, the trend that
  detrending subtracted
- ENH: The dataset list shows only the latest published version of a dataset, so a
  search no longer returns the same dataset once per version
- ENH: Analysis plots are labelled in a unit that suits the data rather than in the
  unit of the first result, so an axis no longer reads `1.000e-4 mm`. Both axes are
  rewritten over one base length unit, keeping a density consistent with its
  abscissa
- PERF: The card endpoint reads the metadata of the first analysis rather than its
  full result. Both are one read of `result.json`, but the latter also fetched every
  data series of that analysis as a separate object, none of which is needed to
  learn its units and labels
- BUG: Task dashboard falls back to the username when a user's name is blank

## 1.0.0 (2026-07-31)

Initial release. This package contains the Django REST Framework
implementation that was previously part of `topobank` and `ce-ui`.

- ENH: Search end points
- ENH: End points for the user and tasks dashboard
- ENH: Asynchronous ZIP download
- ENH: Workflow descriptions are exposed through the API
- BUG: `force_inspect` re-dispatches in-flight tasks (`force=True`)
- BUG: Expose the workflow `visualization_type` so analysis cards render
- BUG: Added `is_staff` to the user serializer
- BUG: Fixed the OpenAPI schema of the `allow` field to use enum values and
  updated the schema for `/entry-points/`
- MAINT: All remaining DRF functionality (serializers, filters, pagination, view
  permissions, upload instructions) moved here from `topobank`
- MAINT: Removed organization management and the REST surfaces for
  organization-based sharing
- MAINT: Removed django-guardian and workflow permission checks
- MAINT: `analysis_function` -> `workflow`, `Folder` -> `ManifestSet`, removal of
  `subject_dispatch`
- BUILD: Build system is hatchling; added django-termsandconditions
