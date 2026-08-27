# ADR 0029: Controlled update architecture

Status: Accepted

PDI separates unprivileged orchestration from privileged deployment execution. The application discovers, validates, plans, preflights, backs up, drains, journals, and displays. An explicit host-side CLI executes the prepared plan. This preserves the proven manual flow without turning the API into a host manager. Blind or automatic updates are rejected.
