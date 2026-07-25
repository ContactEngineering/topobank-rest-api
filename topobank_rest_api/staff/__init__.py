"""
Staff-only dashboards.

These endpoints back the user and task dashboards in the web UI. They are
deliberately kept out of the regular (permission-filtered) API: everything
here is visible to staff users only and bypasses the per-object permission
system, because the whole point is to get an instance-wide view.
"""
