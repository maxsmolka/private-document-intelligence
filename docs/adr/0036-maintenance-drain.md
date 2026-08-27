# ADR 0036: Maintenance and drain mode

Status: Accepted

A single durable control blocks new worker claims and mutable product actions while preserving queued jobs, status, update operations, logout, and read-only account access. Active A2 jobs receive a bounded drain interval and are never killed or deleted. Timeout fails before host mutation and leaves normal operation available.
