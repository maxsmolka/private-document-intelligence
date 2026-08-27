# ADR 0031: Deployment executor boundary

Status: Accepted

The deployment adapter accepts one prepared run and fixed PDI deployment inputs. It exposes no shell, remote endpoint, arbitrary registry, service, project, or image parameter. An operator CLI is safer and more practical for Synology than a privileged long-running helper; future backends may implement the same domain outcome without changing update plans.
